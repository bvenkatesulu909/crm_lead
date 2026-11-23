"""Queries for deal risk snapshots. Always tenant-scoped (and the database enforces it too)."""

import uuid
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

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
