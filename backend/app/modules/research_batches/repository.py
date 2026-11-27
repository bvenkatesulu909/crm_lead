"""Queries of batch research. Every query names the organisation (row-level security is the second
wall, ADR 0009)."""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.research_batches.models import ResearchBatch, ResearchBatchItem


def get(
    session: Session, tenant_id: uuid.UUID, batch_id: uuid.UUID, *, lock: bool = False
) -> ResearchBatch | None:
    query = select(ResearchBatch).where(
        ResearchBatch.tenant_id == tenant_id, ResearchBatch.id == batch_id
    )
    if lock:
        query = query.with_for_update()
    return session.scalars(query).first()


def list_batches(
    session: Session, tenant_id: uuid.UUID, *, limit: int, offset: int
) -> tuple[list[ResearchBatch], int]:
    base = select(ResearchBatch).where(ResearchBatch.tenant_id == tenant_id)
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = session.scalars(
        base.order_by(ResearchBatch.created_at.desc(), ResearchBatch.id).limit(limit).offset(offset)
    )
    return list(rows), int(total)


def items(session: Session, tenant_id: uuid.UUID, batch_id: uuid.UUID) -> list[ResearchBatchItem]:
    return list(
        session.scalars(
            select(ResearchBatchItem)
            .where(ResearchBatchItem.tenant_id == tenant_id, ResearchBatchItem.batch_id == batch_id)
            .order_by(ResearchBatchItem.position)
        )
    )


def running_for_person(session: Session, tenant_id: uuid.UUID, user_id: uuid.UUID) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(ResearchBatch)
            .where(
                ResearchBatch.tenant_id == tenant_id,
                ResearchBatch.created_by_user_id == user_id,
                ResearchBatch.status == "running",
            )
        )
        or 0
    )


def running_for_tenant(session: Session, tenant_id: uuid.UUID) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(ResearchBatch)
            .where(ResearchBatch.tenant_id == tenant_id, ResearchBatch.status == "running")
        )
        or 0
    )


def started_by_person_since(
    session: Session, tenant_id: uuid.UUID, user_id: uuid.UUID, since: datetime
) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(ResearchBatch)
            .where(
                ResearchBatch.tenant_id == tenant_id,
                ResearchBatch.created_by_user_id == user_id,
                ResearchBatch.created_at >= since,
            )
        )
        or 0
    )
