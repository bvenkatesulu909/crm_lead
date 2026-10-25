"""/api/v1/approvals - the approval queue for AI-proposed actions (ADR 0014).

Thin layer: permissions, then the service; write endpoints commit once.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.approvals import service
from app.modules.approvals.models import AgentAction
from app.modules.approvals.schemas import (
    AgentActionPage,
    AgentActionRead,
    Approve,
    Reject,
    Status,
)
from app.modules.identity.api import require_any_permission

router = APIRouter(prefix="/approvals", tags=["approvals"])
Db = Annotated[Session, Depends(get_db_session)]
Reader = Annotated[
    Principal,
    Depends(
        require_any_permission(Permission.AGENT_ACTION_PROPOSE, Permission.AGENT_ACTION_APPROVE)
    ),
]
Approver = Annotated[Principal, Depends(require_any_permission(Permission.AGENT_ACTION_APPROVE))]


def _read(session: Session, principal: Principal, action: AgentAction) -> AgentActionRead:
    return AgentActionRead(
        id=action.id,
        kind=action.kind,
        description=service.describe(action),
        target_type=action.target_type,
        target_id=action.target_id,
        target_link=service.target_link(action),
        target_label=service.target_label(session, principal, action),
        payload=action.payload,
        reason=action.reason,
        agent=action.agent,
        requested_by_user_id=action.requested_by_user_id,
        status=action.status,  # the database allows only these values
        expires_at=action.expires_at,
        decided_by_user_id=action.decided_by_user_id,
        decided_at=action.decided_at,
        decision_note=action.decision_note,
        result=action.result,
        created_at=action.created_at,
        version=action.version,
    )


@router.get(
    "/actions",
    summary="AI proposals: the organisation's for approvers, your own for everyone else",
    responses=problem_responses(422),
)
def list_actions(
    principal: Reader,
    session: Db,
    status: Status | None = None,
    mine: bool = False,
    target_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=100_000),
) -> AgentActionPage:
    items, total = service.list_actions(
        session,
        principal,
        status=status,
        mine=mine,
        target_id=target_id,
        limit=limit,
        offset=offset,
    )
    return AgentActionPage(
        items=[_read(session, principal, a) for a in items], total=total, limit=limit, offset=offset
    )


@router.get("/actions/{action_id}", summary="One AI proposal", responses=problem_responses(404))
def get_action(action_id: uuid.UUID, principal: Reader, session: Db) -> AgentActionRead:
    return _read(session, principal, service.get_action(session, principal, action_id))


@router.post(
    "/actions/{action_id}/approve",
    summary="Approve someone else's AI proposal: the action runs with your rights",
    responses=problem_responses(403, 404, 409, 422),
)
def approve(
    action_id: uuid.UUID, data: Approve, principal: Approver, session: Db
) -> AgentActionRead:
    action = service.approve(session, principal, action_id, version=data.version, note=data.note)
    session.commit()
    return _read(session, principal, action)


@router.post(
    "/actions/{action_id}/reject",
    summary="Reject someone else's AI proposal (a note is required)",
    responses=problem_responses(403, 404, 409, 422),
)
def reject(action_id: uuid.UUID, data: Reject, principal: Approver, session: Db) -> AgentActionRead:
    action = service.reject(session, principal, action_id, version=data.version, note=data.note)
    session.commit()
    return _read(session, principal, action)
