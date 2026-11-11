"""Queries of the web check module. Every query names the tenant (and RLS checks it again)."""

import uuid
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.outbox import OutboxJob
from app.modules.webcheck.models import WebEvidence


def add_evidence(session: Session, evidence: WebEvidence) -> WebEvidence:
    session.add(evidence)
    session.flush()
    return evidence


def get_by_request(
    session: Session, tenant_id: uuid.UUID, request_id: uuid.UUID
) -> WebEvidence | None:
    return session.scalar(
        select(WebEvidence).where(
            WebEvidence.tenant_id == tenant_id, WebEvidence.request_id == request_id
        )
    )


def list_for_target(
    session: Session,
    tenant_id: uuid.UUID,
    target_type: str,
    target_id: uuid.UUID,
    limit: int,
    *,
    source_key: str | None = None,
    without_source: str | None = None,
) -> list[WebEvidence]:
    """Newest first. ``seq`` orders rows that were written in one transaction."""
    query = select(WebEvidence).where(
        WebEvidence.tenant_id == tenant_id,
        WebEvidence.target_type == target_type,
        WebEvidence.target_id == target_id,
    )
    if source_key is not None:
        query = query.where(WebEvidence.source_key == source_key)
    if without_source is not None:
        query = query.where(WebEvidence.source_key != without_source)
    return list(session.scalars(query.order_by(WebEvidence.seq.desc()).limit(limit)))


def count_requests(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    kind: str,
    since: datetime,
    user_id: uuid.UUID | None = None,
) -> int:
    """Checks asked for since a time, counted from the queued jobs: a request counts the moment
    it is made, before the worker has run it (so a burst cannot slip past a limit)."""
    query = (
        select(func.count())
        .select_from(OutboxJob)
        .where(
            OutboxJob.tenant_id == tenant_id, OutboxJob.kind == kind, OutboxJob.created_at >= since
        )
    )
    if user_id is not None:
        query = query.where(OutboxJob.payload["requested_by_user_id"].astext == str(user_id))
    return int(session.scalar(query) or 0)


def delete_older_than(session: Session, tenant_id: uuid.UUID, cutoff: datetime) -> int:
    result = session.execute(
        delete(WebEvidence).where(
            WebEvidence.tenant_id == tenant_id, WebEvidence.created_at < cutoff
        )
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
