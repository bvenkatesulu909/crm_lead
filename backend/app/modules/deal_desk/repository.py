"""Queries of the deal desk (ADR 0024). Always scoped to one organisation."""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.modules.deal_desk.models import DealReview


def add_review(session: Session, review: DealReview) -> DealReview:
    session.add(review)
    session.flush()
    return review


def list_for_deal(
    session: Session, tenant_id: uuid.UUID, opportunity_id: uuid.UUID, limit: int
) -> Sequence[DealReview]:
    return session.scalars(
        select(DealReview)
        .where(DealReview.tenant_id == tenant_id, DealReview.opportunity_id == opportunity_id)
        .order_by(DealReview.seq.desc())
        .limit(limit)
    ).all()


def delete_older_than(session: Session, tenant_id: uuid.UUID, cutoff: datetime) -> int:
    result = session.execute(
        delete(DealReview).where(DealReview.tenant_id == tenant_id, DealReview.created_at < cutoff)
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
