"""Queries of the approval queue, always inside one tenant (RLS is bound too)."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, and_, func, or_, select
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


def count_since(
    session: Session,
    tenant_id: uuid.UUID,
    *,
    since: datetime,
    requester: uuid.UUID | None = None,
    kind: str | None = None,
    target_id: uuid.UUID | None = None,
    agent: str | None = None,
) -> int:
    """Proposals made since a moment, however they ended (history counts: a flood of rejected
    proposals is still a flood)."""
    conditions = [AgentAction.tenant_id == tenant_id, AgentAction.created_at >= since]
    if requester is not None:
        conditions.append(AgentAction.requested_by_user_id == requester)
    if kind is not None:
        conditions.append(AgentAction.kind == kind)
    if target_id is not None:
        conditions.append(AgentAction.target_id == target_id)
    if agent is not None:
        conditions.append(AgentAction.agent == agent)
    return session.scalar(select(func.count()).select_from(AgentAction).where(*conditions)) or 0


def identical_pending(
    session: Session,
    tenant_id: uuid.UUID,
    *,
    kind: str,
    target_id: uuid.UUID,
    payload: dict[str, Any],
) -> bool:
    return (
        session.scalar(
            select(func.count())
            .select_from(AgentAction)
            .where(
                AgentAction.tenant_id == tenant_id,
                AgentAction.status == "pending",
                AgentAction.kind == kind,
                AgentAction.target_id == target_id,
                AgentAction.payload == payload,
            )
        )
        or 0
    ) > 0


def page(
    session: Session,
    tenant_id: uuid.UUID,
    *,
    status: str | None,
    requester: uuid.UUID | None,
    target_id: uuid.UUID | None = None,
    owner_decides: tuple[frozenset[str], list[Any]] | None = None,
    limit: int,
    offset: int,
) -> tuple[list[AgentAction], int]:
    conditions = [AgentAction.tenant_id == tenant_id]
    if target_id is not None:
        conditions.append(AgentAction.target_id == target_id)
    if status is not None:
        conditions.append(AgentAction.status == status)
    if requester is not None:
        mine = AgentAction.requested_by_user_id == requester
        kinds, owned = owner_decides if owner_decides is not None else (frozenset(), [])
        # Plus the kinds the owner of the record may decide on, for records they own.
        also = [
            and_(
                AgentAction.kind.in_(kinds),
                AgentAction.target_type == target_type,
                AgentAction.target_id.in_(owned_ids),
            )
            for target_type, owned_ids in owned
        ]
        conditions.append(or_(mine, *also))
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


# --- follow-up drafts (ADR 0036) -------------------------------------------------------------


@dataclass(frozen=True)
class DraftHistory:
    waiting: bool
    last_at: datetime | None
    in_window: int


def draft_history(
    session: Session, tenant_id: uuid.UUID, kind: str, target_id: uuid.UUID, since: datetime
) -> DraftHistory:
    """What the drafts of one kind for one record look like: is one waiting, when was the newest
    made, and how many were made since ``since`` (however they ended)."""
    rows = session.execute(
        select(AgentAction.created_at, AgentAction.status).where(
            AgentAction.tenant_id == tenant_id,
            AgentAction.kind == kind,
            AgentAction.target_id == target_id,
        )
    ).all()
    return DraftHistory(
        waiting=any(r.status == "pending" for r in rows),
        last_at=max((r.created_at for r in rows), default=None),
        in_window=sum(1 for r in rows if r.created_at >= since),
    )


def waiting_for_targets(
    session: Session, tenant_id: uuid.UUID, kind: str, targets: Select[Any]
) -> int:
    """Undecided proposals of one kind whose record is in ``targets`` (a subquery of ids)."""
    return (
        session.scalar(
            select(func.count())
            .select_from(AgentAction)
            .where(
                AgentAction.tenant_id == tenant_id,
                AgentAction.kind == kind,
                AgentAction.status == "pending",
                AgentAction.target_id.in_(targets),
            )
        )
        or 0
    )
