"""Knowledge endpoints: staff upload, list, inspect status and delete (RAG R1).

Thin layer: RBAC permission, then the service (tenant-scoped policy), commit once.
"""

import time
import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.core.observability.metrics import (
    RAG_ANSWERS,
    RAG_SEARCH_DURATION,
    RAG_SEARCHES,
)
from app.core.storage import FileStore, get_file_store
from app.modules.identity.api import granted_account_ids, require_any_permission
from app.modules.knowledge import answers, repository, retrieval, rules, service
from app.modules.knowledge.models import KnowledgeDocument
from app.modules.knowledge.schemas import (
    KnowledgeAnswerRequest,
    KnowledgeAnswerResponse,
    KnowledgeAnswerSource,
    KnowledgeDocumentList,
    KnowledgeDocumentRead,
    KnowledgeSearchHit,
    KnowledgeSearchResponse,
    RagFeedbackCreate,
)

router = APIRouter(prefix="/knowledge", tags=["knowledge"], responses=problem_responses(401, 403))
portal_router = APIRouter(
    prefix="/portal/knowledge",
    tags=["portal-knowledge"],
    responses=problem_responses(401, 403),
)
Reader = Annotated[Principal, Depends(require_any_permission(Permission.KNOWLEDGE_READ))]
Manager = Annotated[Principal, Depends(require_any_permission(Permission.KNOWLEDGE_MANAGE))]
PortalCustomer = Annotated[
    Principal, Depends(require_any_permission(Permission.PORTAL_KNOWLEDGE_READ))
]
Db = Annotated[Session, Depends(get_db_session)]
Files = Annotated[FileStore, Depends(get_file_store)]


def _read(document: KnowledgeDocument, chunks: int) -> KnowledgeDocumentRead:
    return KnowledgeDocumentRead(
        id=document.id,
        title=document.title,
        file_name=document.file_name,
        content_type=document.content_type,
        size_bytes=document.size_bytes,
        status=document.status,
        visibility=document.visibility,
        account_id=document.account_id,
        group_id=document.group_id,
        version=document.version,
        is_archived=document.is_archived,
        page_count=document.page_count,
        chunk_count=chunks,
        error=document.error,
        created_at=document.created_at,
    )


@router.get("/documents", summary="Knowledge documents and their indexing status")
def list_documents(
    principal: Reader,
    session: Db,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> KnowledgeDocumentList:
    documents, total = service.list_documents(
        session, principal, status=status_filter, limit=limit, offset=offset
    )
    items = [
        _read(document, repository.chunk_count(session, document.tenant_id, document.id))
        for document in documents
    ]
    return KnowledgeDocumentList(items=items, total=total)


@router.get(
    "/search",
    summary="Search the knowledge base (meaning + keyword search, RRF-fused)",
    responses=problem_responses(422, 503),
)
def search_knowledge(
    principal: Reader,
    session: Db,
    request: Request,
    q: Annotated[str, Query(min_length=1, max_length=500)],
    limit: Annotated[int | None, Query(ge=1, le=20)] = None,
) -> KnowledgeSearchResponse:
    settings = request.app.state.settings
    started = time.perf_counter()
    outcome = retrieval.search(
        session,
        principal,
        request.app.state.embedder,
        query=q,
        candidates=settings.knowledge_candidates,
        rrf_k=settings.knowledge_rrf_k,
        top_k=limit or settings.knowledge_top_k,
        min_similarity=settings.knowledge_min_similarity,
        reranker=request.app.state.reranker,
        rerank_candidates=settings.knowledge_rerank_candidates,
    )
    RAG_SEARCH_DURATION.labels(stage="retrieval").observe(time.perf_counter() - started)
    RAG_SEARCHES.labels(outcome="results" if outcome.results else "empty").inc()
    return KnowledgeSearchResponse(
        query=outcome.query,
        results=[
            KnowledgeSearchHit(
                chunk_id=hit.chunk_id,
                document_id=hit.document_id,
                document_title=hit.document_title,
                file_name=hit.file_name,
                heading_path=hit.heading_path,
                page_from=hit.page_from,
                page_to=hit.page_to,
                text=hit.text,
                blocks=hit.blocks,
                visibility=hit.visibility,
                similarity=hit.similarity,
                keyword_rank=hit.keyword_rank,
                score=hit.score,
                rerank_score=hit.rerank_score,
            )
            for hit in outcome.results
        ],
        best_similarity=outcome.best_similarity,
        threshold=outcome.threshold,
        enough=outcome.enough,
    )


@router.post(
    "/answer",
    summary="Answer a question from the knowledge base, with citations",
    responses=problem_responses(422, 503),
)
def answer_knowledge(
    principal: Reader,
    session: Db,
    request: Request,
    body: KnowledgeAnswerRequest,
) -> KnowledgeAnswerResponse:
    settings = request.app.state.settings
    started = time.perf_counter()
    outcome = answers.answer_question(
        session,
        principal,
        request.app.state.embedder,
        request.app.state.chat_model,
        question=body.question,
        settings=settings,
        reranker=request.app.state.reranker,
    )
    query_id = service.record_rag_query(
        session,
        principal,
        surface="staff_answer",
        question=body.question,
        answer=outcome.answer,
        sources=[
            {"document": source.document_title, "heading": source.heading_path}
            for source in outcome.sources
        ],
    )
    session.commit()
    query_id = service.record_rag_query(
        session,
        principal,
        surface="staff_answer",
        question=body.question,
        answer=outcome.answer,
        sources=[
            {"document": source.document_title, "heading": source.heading_path}
            for source in outcome.sources
        ],
    )
    session.commit()
    RAG_SEARCH_DURATION.labels(stage="answer").observe(time.perf_counter() - started)
    answer_outcome = (
        "answered" if outcome.grounded else "ungrounded" if outcome.model_used else "refused"
    )
    RAG_ANSWERS.labels(outcome=answer_outcome).inc()
    return KnowledgeAnswerResponse(
        query_id=query_id,
        answer=outcome.answer,
        sources=[
            KnowledgeAnswerSource(
                chunk_id=source.chunk_id,
                document_id=source.document_id,
                document_title=source.document_title,
                heading_path=source.heading_path,
                page_from=source.page_from,
                page_to=source.page_to,
                text=source.text,
            )
            for source in outcome.sources
        ],
        exact_chunk_id=outcome.exact_chunk_id,
        enough=outcome.enough,
        model_used=outcome.model_used,
        grounded=outcome.grounded,
        citations=outcome.citations,
    )


@router.post(
    "/documents",
    status_code=status.HTTP_201_CREATED,
    summary="Upload a PDF, DOCX, TXT or Markdown document for indexing",
    responses=problem_responses(409, 413, 415, 422, 503),
)
async def upload_document(
    request: Request,
    principal: Manager,
    session: Db,
    files: Files,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form()] = None,
    visibility: Annotated[str, Form()] = "internal",
    account_id: Annotated[str | None, Form()] = None,
    replaces_document_id: Annotated[str | None, Form()] = None,
) -> KnowledgeDocumentRead:
    settings = request.app.state.settings
    data = await file.read(settings.files_max_bytes + 1)
    name = rules.clean_file_name(file.filename)
    document = service.create_document(
        session,
        principal,
        files,
        title=title or rules.title_from(name),
        file_name=name,
        content_type=file.content_type or "",
        data=data,
        max_bytes=settings.files_max_bytes,
        visibility=visibility,
        account_id=uuid.UUID(account_id) if account_id else None,
        replaces_document_id=(uuid.UUID(replaces_document_id) if replaces_document_id else None),
    )
    session.commit()
    session.refresh(document)
    return _read(document, 0)


@router.get("/documents/{document_id}", summary="One knowledge document with its status")
def get_document(document_id: uuid.UUID, principal: Reader, session: Db) -> KnowledgeDocumentRead:
    document = service.get_document(session, principal, document_id)
    return _read(document, repository.chunk_count(session, document.tenant_id, document.id))


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a knowledge document, its chunks and its stored file",
    responses=problem_responses(404),
)
def delete_document(document_id: uuid.UUID, principal: Manager, session: Db, files: Files) -> None:
    service.delete_document(session, principal, files, document_id)
    session.commit()


@router.post(
    "/documents/{document_id}/archive",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Archive a document and delete its chunks in the same transaction",
    responses=problem_responses(404),
)
def archive_document_endpoint(document_id: uuid.UUID, principal: Manager, session: Db) -> None:
    service.archive_document(session, principal, document_id)
    session.commit()


@portal_router.post(
    "/answer",
    summary="Answer a question from knowledge shared with this customer",
    responses=problem_responses(422, 503),
)
def portal_answer_knowledge(
    principal: PortalCustomer,
    session: Db,
    request: Request,
    body: KnowledgeAnswerRequest,
) -> KnowledgeAnswerResponse:
    """Customer scope: customer_visible chunks with no account, plus granted accounts only."""
    if principal.user_type != "customer":
        raise HTTPException(status_code=403, detail="The portal is for customers.")
    account_ids = list(session.scalars(granted_account_ids(principal)).all())
    settings = request.app.state.settings
    started = time.perf_counter()
    outcome = answers.answer_question(
        session,
        principal,
        request.app.state.embedder,
        request.app.state.chat_model,
        question=body.question,
        settings=settings,
        reranker=request.app.state.reranker,
        account_ids=account_ids,
    )
    query_id = service.record_rag_query(
        session,
        principal,
        surface="portal_answer",
        question=body.question,
        answer=outcome.answer,
        sources=[
            {"document": source.document_title, "heading": source.heading_path}
            for source in outcome.sources
        ],
    )
    session.commit()
    RAG_SEARCH_DURATION.labels(stage="portal_answer").observe(time.perf_counter() - started)
    answer_outcome = (
        "answered" if outcome.grounded else "ungrounded" if outcome.model_used else "refused"
    )
    RAG_ANSWERS.labels(outcome=answer_outcome).inc()
    return KnowledgeAnswerResponse(
        query_id=query_id,
        answer=outcome.answer,
        sources=[
            KnowledgeAnswerSource(
                chunk_id=source.chunk_id,
                document_id=source.document_id,
                document_title=source.document_title,
                heading_path=source.heading_path,
                page_from=source.page_from,
                page_to=source.page_to,
                text=source.text,
            )
            for source in outcome.sources
        ],
        exact_chunk_id=outcome.exact_chunk_id,
        enough=outcome.enough,
        model_used=outcome.model_used,
        grounded=outcome.grounded,
        citations=outcome.citations,
    )


@router.post(
    "/feedback",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Was this knowledge answer helpful?",
    responses=problem_responses(404),
)
def staff_feedback(principal: Reader, session: Db, body: RagFeedbackCreate) -> None:
    service.record_rag_feedback(session, principal, body.query_id, body.helpful)
    session.commit()


@portal_router.post(
    "/feedback",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Was this portal answer helpful?",
    responses=problem_responses(404),
)
def portal_feedback(principal: PortalCustomer, session: Db, body: RagFeedbackCreate) -> None:
    service.record_rag_feedback(session, principal, body.query_id, body.helpful)
    session.commit()
