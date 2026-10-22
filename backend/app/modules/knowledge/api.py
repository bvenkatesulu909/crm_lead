"""Public interface of the knowledge module: the outbox job handler (RAG R1)."""

import uuid
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.core.ai.embeddings import Embedder
from app.core.auth.principal import Principal
from app.core.outbox import Job, JobHandler
from app.core.storage import FileStore
from app.modules.knowledge import service

JOB_KIND = service.JOB_KIND


def run_maintenance(
    session_factory: sessionmaker[Session], *, embedding_model: str
) -> Any:
    from app.modules.knowledge import freshness

    return freshness.run_daily_maintenance(session_factory, embedding_model=embedding_model)


def erase_user_rag_queries(
    session: Session, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> int:
    from app.modules.knowledge import freshness

    return freshness.erase_user_queries(session, tenant_id, user_id)


def ingest_handler(store: FileStore, embedder: Embedder) -> JobHandler:
    """Worker handler factory: bytes from the file store, embeddings from the local model."""

    def handler(session: Session, job: Job) -> None:
        document_id = uuid.UUID(str(job.payload["document_id"]))
        service.ingest_document(
            session,
            store,
            embedder,
            tenant_id=job.tenant_id,
            document_id=document_id,
        )

    return handler


def search_help_articles(
    session: Session,
    principal: Principal,
    question: str,
    *,
    account_ids: list[uuid.UUID],
    limit: int = 3,
) -> list[dict[str, object]]:
    """Keyword help search with the PORTAL scope (public + granted accounts only)."""
    from sqlalchemy import and_, func, or_, select

    from app.modules.knowledge.models import KnowledgeChunk, KnowledgeDocument

    if principal.tenant_id is None:
        return []
    tsquery = func.websearch_to_tsquery("simple", question)
    statement = (
        select(
            KnowledgeDocument.title,
            KnowledgeDocument.file_name,
            KnowledgeChunk.heading_path,
            KnowledgeChunk.text,
            KnowledgeChunk.page_from,
        )
        .join(
            KnowledgeDocument,
            and_(
                KnowledgeDocument.tenant_id == KnowledgeChunk.tenant_id,
                KnowledgeDocument.id == KnowledgeChunk.document_id,
            ),
        )
        .where(
            KnowledgeDocument.tenant_id == principal.tenant_id,
            KnowledgeDocument.status == "indexed",
            KnowledgeDocument.visibility == "customer_visible",
            KnowledgeChunk.visibility == "customer_visible",
            or_(
                KnowledgeDocument.account_id.is_(None),
                KnowledgeDocument.account_id.in_(account_ids),
            ),
            KnowledgeChunk.tsv.op("@@")(tsquery),
        )
        .order_by(func.ts_rank_cd(KnowledgeChunk.tsv, tsquery).desc())
        .limit(limit)
    )
    return [
        {
            "document": row.title,
            "file_name": row.file_name,
            "heading": row.heading_path,
            "page": row.page_from,
            "text": row.text,
        }
        for row in session.execute(statement).all()
    ]


def answer_customer_scope(
    session: Session,
    principal: Principal,
    *,
    question: str,
    account_ids: list[uuid.UUID],
    settings: Any,
    embedder: Embedder,
    chat_model: Any,
    reranker: Any = None,
) -> Any:
    """Answer with customer visibility (used by staff ticket reply drafts)."""
    from dataclasses import replace

    from app.modules.knowledge import answers

    scoped = replace(principal, user_type="customer")
    return answers.answer_question(
        session,
        scoped,
        embedder,
        chat_model,
        question=question,
        settings=settings,
        reranker=reranker,
        account_ids=account_ids,
    )
