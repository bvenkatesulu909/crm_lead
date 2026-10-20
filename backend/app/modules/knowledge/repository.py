"""Tenant-scoped database access for knowledge documents and chunks (RAG R1)."""

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.repository import TenantScopedRepository
from app.modules.knowledge.chunking import CHUNKING_VERSION, Chunk
from app.modules.knowledge.models import KnowledgeChunk, KnowledgeDocument
from app.modules.knowledge.policies import readable_documents


def list_documents(
    session: Session,
    principal: Principal,
    *,
    status: str | None = None,
    limit: int,
    offset: int,
) -> tuple[Sequence[KnowledgeDocument], int]:
    scoped = TenantScopedRepository(session, principal)
    statement = scoped.scoped_select(KnowledgeDocument).where(readable_documents(principal))
    if status is not None:
        statement = statement.where(KnowledgeDocument.status == status)
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    page = (
        statement.order_by(KnowledgeDocument.created_at.desc(), KnowledgeDocument.id)
        .limit(limit)
        .offset(offset)
    )
    return session.scalars(page).all(), total


def get_document(
    session: Session, principal: Principal, document_id: uuid.UUID
) -> KnowledgeDocument | None:
    scoped = TenantScopedRepository(session, principal)
    return scoped.get_or_none(KnowledgeDocument, document_id, readable_documents(principal))


def get_document_for_worker(
    session: Session, tenant_id: uuid.UUID, document_id: uuid.UUID
) -> KnowledgeDocument | None:
    return session.scalars(
        select(KnowledgeDocument).where(
            KnowledgeDocument.tenant_id == tenant_id, KnowledgeDocument.id == document_id
        )
    ).one_or_none()


def chunk_count(session: Session, tenant_id: uuid.UUID, document_id: uuid.UUID) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(KnowledgeChunk)
            .where(
                KnowledgeChunk.tenant_id == tenant_id,
                KnowledgeChunk.document_id == document_id,
            )
        )
        or 0
    )


def replace_chunks(
    session: Session,
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
    chunks: Sequence[Chunk],
) -> None:
    """Replace every chunk of a document in the caller's transaction (idempotent re-ingest)."""
    session.execute(
        delete(KnowledgeChunk).where(
            KnowledgeChunk.tenant_id == tenant_id,
            KnowledgeChunk.document_id == document_id,
        )
    )
    for number, chunk in enumerate(chunks, start=1):
        session.add(
            KnowledgeChunk(
                tenant_id=tenant_id,
                document_id=document_id,
                chunk_no=number,
                text=chunk.text,
                blocks=chunk.blocks,
                heading_path=chunk.heading_path,
                page_from=chunk.page_from,
                page_to=chunk.page_to,
                char_count=chunk.char_count,
                chunking_version=CHUNKING_VERSION,
            )
        )
