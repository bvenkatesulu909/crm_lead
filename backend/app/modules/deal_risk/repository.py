"""Queries for deal risk snapshots. Always tenant-scoped (and the database enforces it too)."""

import uuid
from datetime import datetime

from sqlalchemy import Select, delete, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session, aliased

from app.modules.deal_risk.models import DealRiskSnapshot


def add(session: Session, snapshot: DealRiskSnapshot) -> DealRiskSnapshot:
    session.add(snapshot)
    session.flush()
    return snapshot


def latest(
    session: Session, tenant_id: uuid.UUID, opportunity_id: uuid.UUID
) -> DealRiskSnapshot | None:
    return session.scalars(
        select(DealRiskSnapshot)
        .where(
            DealRiskSnapshot.tenant_id == tenant_id,
            DealRiskSnapshot.opportunity_id == opportunity_id,
        )
        .order_by(DealRiskSnapshot.seq.desc())
        .limit(1)
    ).one_or_none()


def history(
    session: Session, tenant_id: uuid.UUID, opportunity_id: uuid.UUID, limit: int
) -> list[DealRiskSnapshot]:
    return list(
        session.scalars(
            select(DealRiskSnapshot)
            .where(
                DealRiskSnapshot.tenant_id == tenant_id,
                DealRiskSnapshot.opportunity_id == opportunity_id,
            )
            .order_by(DealRiskSnapshot.seq.desc())
            .limit(limit)
        ).all()
    )


def nightly_done_for(session: Session, tenant_id: uuid.UUID, since: datetime) -> set[uuid.UUID]:
    return set(
        session.scalars(
            select(DealRiskSnapshot.opportunity_id).where(
                DealRiskSnapshot.tenant_id == tenant_id,
                DealRiskSnapshot.source == "nightly",
                DealRiskSnapshot.created_at >= since,
            )
        ).all()
    )


def delete_older_than(session: Session, tenant_id: uuid.UUID, cutoff: datetime) -> int:
    result = session.execute(
        delete(DealRiskSnapshot).where(
            DealRiskSnapshot.tenant_id == tenant_id, DealRiskSnapshot.created_at < cutoff
        )
    )
    return result.rowcount or 0  # type: ignore[attr-defined]


def count_on_demand_since(session: Session, user_id: uuid.UUID, since: datetime) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(DealRiskSnapshot)
            .where(
                DealRiskSnapshot.source == "on_demand",
                DealRiskSnapshot.requested_by_user_id == user_id,
                DealRiskSnapshot.created_at >= since,
            )
        )
        or 0
    )


def latest_per_deal(
    session: Session,
    tenant_id: uuid.UUID,
    visible_deal_ids: Select[uuid.UUID],
    *,
    level: str | None,
    limit: int,
    offset: int,
) -> tuple[list[DealRiskSnapshot], int]:
    """The newest snapshot of each visible deal, highest score first, with the total count.

    The caller passes the deals the person may read as a subquery, so the filtering happens in
    SQL (never after loading)."""
    newest = (
        select(DealRiskSnapshot)
        .where(
            DealRiskSnapshot.tenant_id == tenant_id,
            DealRiskSnapshot.opportunity_id.in_(visible_deal_ids),
        )
        .ext(distinct_on(DealRiskSnapshot.opportunity_id))
        .order_by(DealRiskSnapshot.opportunity_id, DealRiskSnapshot.seq.desc())
        .subquery()
    )
    row = aliased(DealRiskSnapshot, newest)
    filters = [row.level == level] if level else []
    total = session.scalar(select(func.count()).select_from(row).where(*filters)) or 0
    rows = session.scalars(
        select(row)
        .where(*filters)
        .order_by(row.score.desc(), row.seq.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return list(rows), total


def levels_before(
    session: Session, tenant_id: uuid.UUID, closed: dict[uuid.UUID, datetime]
) -> dict[uuid.UUID, str]:
    """For each deal, the level of its newest snapshot taken BEFORE it closed (a forecast made
    while it was still open). Deals without one are left out."""
    if not closed:
        return {}
    rows = session.execute(
        select(DealRiskSnapshot.opportunity_id, DealRiskSnapshot.level, DealRiskSnapshot.created_at)
        .where(
            DealRiskSnapshot.tenant_id == tenant_id,
            DealRiskSnapshot.opportunity_id.in_(list(closed)),
        )
        .order_by(DealRiskSnapshot.seq)
    ).all()
    levels: dict[uuid.UUID, str] = {}
    for deal, level, created_at in rows:
        if created_at < closed[deal]:
            levels[deal] = level  # later rows overwrite earlier ones: the newest before closing
    return levels
