"""Queries of the approval queue, always inside one tenant (RLS is bound too)."""

import uuid

from sqlalchemy import select
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
