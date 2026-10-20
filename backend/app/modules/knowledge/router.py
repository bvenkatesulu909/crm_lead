"""Knowledge endpoints: staff upload, list, inspect status and delete (RAG R1).

Thin layer: RBAC permission, then the service (tenant-scoped policy), commit once.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.core.storage import FileStore, get_file_store
from app.modules.identity.api import require_any_permission
from app.modules.knowledge import repository, rules, service
from app.modules.knowledge.models import KnowledgeDocument
from app.modules.knowledge.schemas import KnowledgeDocumentList, KnowledgeDocumentRead

router = APIRouter(prefix="/knowledge", tags=["knowledge"], responses=problem_responses(401, 403))
Reader = Annotated[Principal, Depends(require_any_permission(Permission.KNOWLEDGE_READ))]
Manager = Annotated[Principal, Depends(require_any_permission(Permission.KNOWLEDGE_MANAGE))]
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
