"""Queries of call recordings. Every query names the tenant (and RLS checks it again)."""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.calls.models import CallRecording


def add(session: Session, row: CallRecording) -> CallRecording:
    session.add(row)
    session.flush()
    return row


def list_of_lead(session: Session, tenant_id: uuid.UUID, lead_id: uuid.UUID) -> list[CallRecording]:
    """Newest first (``created_at`` ties are broken by id so the order is stable)."""
    return list(
        session.scalars(
            select(CallRecording)
            .where(CallRecording.tenant_id == tenant_id, CallRecording.lead_id == lead_id)
            .order_by(CallRecording.created_at.desc(), CallRecording.id.desc())
        )
    )


def get_of_lead(
    session: Session, tenant_id: uuid.UUID, lead_id: uuid.UUID, call_id: uuid.UUID
) -> CallRecording | None:
    return session.scalar(
        select(CallRecording).where(
            CallRecording.tenant_id == tenant_id,
            CallRecording.lead_id == lead_id,
            CallRecording.id == call_id,
        )
    )


def lock_of_lead(
    session: Session, tenant_id: uuid.UUID, lead_id: uuid.UUID, call_id: uuid.UUID
) -> CallRecording | None:
    return session.scalar(
        select(CallRecording)
        .where(
            CallRecording.tenant_id == tenant_id,
            CallRecording.lead_id == lead_id,
            CallRecording.id == call_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def count_started(
    session: Session,
    tenant_id: uuid.UUID,
    since: datetime,
    *,
    user_id: uuid.UUID | None = None,
) -> int:
    statement = (
        select(func.count())
        .select_from(CallRecording)
        .where(CallRecording.tenant_id == tenant_id, CallRecording.created_at >= since)
    )
    if user_id is not None:
        statement = statement.where(CallRecording.added_by_user_id == user_id)
    return int(session.scalar(statement) or 0)


def stale_uploads(session: Session, tenant_id: uuid.UUID, before: datetime) -> list[CallRecording]:
    return list(
        session.scalars(
            select(CallRecording).where(
                CallRecording.tenant_id == tenant_id,
                CallRecording.status == "uploading",
                CallRecording.created_at < before,
            )
        )
    )
