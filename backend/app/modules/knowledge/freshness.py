"""Nightly knowledge freshness, retention and erasure helpers (R6.2/R6.3)."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import bind_tenant
from app.core.heartbeat import ServiceHeartbeat
from app.modules.identity.models import Tenant
from app.modules.knowledge.models import KnowledgeChunk, KnowledgeDocument, RagQuery

logger = logging.getLogger(__name__)

RETENTION_DAYS = 90
STUCK_MINUTES = 30
HEARTBEAT = "knowledge-maintenance"


def maintenance_for_tenant(
    session: Session,
    tenant_id: uuid.UUID,
    *,
    embedding_model: str,
    now: datetime | None = None,
    retention_days: int = RETENTION_DAYS,
    stuck_minutes: int = STUCK_MINUTES,
) -> dict[str, int]:
    now = now or datetime.now(UTC)
    stuck_before = now - timedelta(minutes=stuck_minutes)
    missing = (
        session.scalar(
            select(func.count())
            .select_from(KnowledgeDocument)
            .outerjoin(KnowledgeChunk, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .where(
                KnowledgeDocument.tenant_id == tenant_id,
                KnowledgeDocument.is_archived.is_(False),
                KnowledgeDocument.status == "indexed",
                KnowledgeChunk.id.is_(None),
            )
        )
        or 0
    )
    archived_chunks = (
        session.scalar(
            select(func.count())
            .select_from(KnowledgeChunk)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(KnowledgeChunk.tenant_id == tenant_id, KnowledgeDocument.is_archived.is_(True))
        )
        or 0
    )
    old_model = (
        session.scalar(
            select(func.count())
            .select_from(KnowledgeChunk)
            .where(
                KnowledgeChunk.tenant_id == tenant_id,
                KnowledgeChunk.embedding_model.is_not(None),
                KnowledgeChunk.embedding_model != embedding_model,
            )
        )
        or 0
    )
    stuck = (
        session.scalar(
            select(func.count())
            .select_from(KnowledgeDocument)
            .where(
                KnowledgeDocument.tenant_id == tenant_id,
                KnowledgeDocument.status == "processing",
                KnowledgeDocument.created_at < stuck_before,
            )
        )
        or 0
    )
    deleted_result = session.execute(
        delete(RagQuery).where(
            RagQuery.tenant_id == tenant_id,
            RagQuery.created_at < now - timedelta(days=retention_days),
        )
    )
    deleted = int(getattr(deleted_result, "rowcount", 0) or 0)
    report = {
        "published_without_chunks": int(missing),
        "chunks_of_archived_documents": int(archived_chunks),
        "chunks_from_old_embedding_model": int(old_model),
        "documents_stuck_processing": int(stuck),
        "rag_queries_deleted": int(deleted),
    }
    if any(
        report[key]
        for key in (
            "published_without_chunks",
            "chunks_of_archived_documents",
            "chunks_from_old_embedding_model",
            "documents_stuck_processing",
        )
    ):
        logger.warning("knowledge freshness issues", extra={"tenant_id": str(tenant_id), **report})
    return report


def run_daily_maintenance(
    session_factory: sessionmaker[Session],
    *,
    embedding_model: str,
    interval_hours: int = 24,
    now: datetime | None = None,
) -> dict[str, dict[str, int]] | None:
    now = now or datetime.now(UTC)
    with session_factory() as session:
        heartbeat = session.get(ServiceHeartbeat, HEARTBEAT)
        if heartbeat is not None and heartbeat.last_seen > now - timedelta(hours=interval_hours):
            return None
        tenants = session.scalars(select(Tenant)).all()
    results: dict[str, dict[str, int]] = {}
    for tenant in tenants:
        with session_factory() as session, session.begin():
            bind_tenant(session, tenant.id)
            results[tenant.slug] = maintenance_for_tenant(
                session, tenant.id, embedding_model=embedding_model, now=now
            )
    with session_factory() as session, session.begin():
        session.execute(
            insert(ServiceHeartbeat)
            .values(name=HEARTBEAT, last_seen=now)
            .on_conflict_do_update(index_elements=[ServiceHeartbeat.name], set_={"last_seen": now})
        )
    logger.info("knowledge maintenance finished", extra={"tenants": len(tenants)})
    return results


def erase_user_queries(session: Session, tenant_id: uuid.UUID, user_id: uuid.UUID) -> int:
    result = session.execute(
        delete(RagQuery).where(RagQuery.tenant_id == tenant_id, RagQuery.user_id == user_id)
    )
    return int(getattr(result, "rowcount", 0) or 0)
