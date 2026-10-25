"""Queries of the approval queue, always inside one tenant (RLS is bound too)."""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.approvals.models import AgentAction


def get(session: Session, tenant_id: uuid.UUID, action_id: uuid.UUID) -> AgentAction | None:
    return session.scalars(
        select(AgentAction).where(AgentAction.tenant_id == tenant_id, AgentAction.id == action_id)
    ).one_or_none()


def lock(session: Session, tenant_id: uuid.UUID, action_id: uuid.UUID) -> AgentAction | None:
    """The proposal, locked until the transaction ends: two approvers clicking at the same
    moment are handled one after the other, and only the first decision counts."""
    return session.scalars(
        select(AgentAction)
        .where(AgentAction.tenant_id == tenant_id, AgentAction.id == action_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one_or_none()


def pending_count(session: Session, tenant_id: uuid.UUID, requester: uuid.UUID) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(AgentAction)
            .where(
                AgentAction.tenant_id == tenant_id,
                AgentAction.requested_by_user_id == requester,
                AgentAction.status == "pending",
            )
        )
        or 0
    )


def page(
    session: Session,
    tenant_id: uuid.UUID,
    *,
    status: str | None,
    requester: uuid.UUID | None,
    target_id: uuid.UUID | None = None,
    limit: int,
    offset: int,
) -> tuple[list[AgentAction], int]:
    conditions = [AgentAction.tenant_id == tenant_id]
    if target_id is not None:
        conditions.append(AgentAction.target_id == target_id)
    if status is not None:
        conditions.append(AgentAction.status == status)
    if requester is not None:
        conditions.append(AgentAction.requested_by_user_id == requester)
    total = session.scalar(select(func.count()).select_from(AgentAction).where(*conditions)) or 0
    items = session.scalars(
        select(AgentAction)
        .where(*conditions)
        .order_by(AgentAction.seq.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return list(items), total


def due_for_expiry(session: Session, tenant_id: uuid.UUID, now: datetime) -> Sequence[AgentAction]:
    return session.scalars(
        select(AgentAction)
        .where(
            AgentAction.tenant_id == tenant_id,
            AgentAction.status == "pending",
            AgentAction.expires_at <= now,
        )
        # Skip rows an approver is deciding on right now; the next run takes them.
        .with_for_update(skip_locked=True)
    ).all()
