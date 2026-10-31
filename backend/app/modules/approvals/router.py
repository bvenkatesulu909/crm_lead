"""/api/v1/approvals - the approval queue for AI-proposed actions (ADR 0014).

Thin layer: permissions, then the service; write endpoints commit once.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.auth.tokens import VerifiedToken
from app.core.config import Settings
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.agents import api as agents_api
from app.modules.approvals import sentinel, service
from app.modules.approvals.models import AgentAction
from app.modules.approvals.schemas import (
    ActionOutcome,
    AgentActionPage,
    AgentActionRead,
    Approve,
    ExternalProposal,
    PlannedChange,
    Reject,
    SafetyWarning,
    SeenValue,
    Status,
)
from app.modules.identity.api import get_verified_token, require_any_permission

router = APIRouter(prefix="/approvals", tags=["approvals"])
Db = Annotated[Session, Depends(get_db_session)]
Reader = Annotated[
    Principal,
    Depends(
        require_any_permission(Permission.AGENT_ACTION_PROPOSE, Permission.AGENT_ACTION_APPROVE)
    ),
]
Proposer = Annotated[Principal, Depends(require_any_permission(Permission.AGENT_ACTION_PROPOSE))]
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
        via_client=action.via_client,
        requested_by_user_id=action.requested_by_user_id,
        status=action.status,  # the database allows only these values
        expires_at=action.expires_at,
        decided_by_user_id=action.decided_by_user_id,
        decided_at=action.decided_at,
        decision_note=action.decision_note,
        result=action.result,
        warnings=[SafetyWarning(**w) for w in (action.verification or {}).get("warnings", [])],
        changes=[PlannedChange(**c) for c in _stored(action).get("spec", {}).get("changes", [])],
        outcome=_outcome(_stored(action).get("outcome")),
        created_at=action.created_at,
        version=action.version,
    )


def _stored(action: AgentAction) -> dict[str, Any]:
    return action.verification or {}


def _outcome(raw: dict[str, Any] | None) -> ActionOutcome | None:
    if raw is None:
        return None
    return ActionOutcome(
        ran=raw["ran"],
        matches_plan=raw.get("matches_spec"),
        differs=raw.get("differs", []),
        seen=[SeenValue(**v) for v in raw.get("seen", [])],
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


@router.post(
    "/proposals/external",
    status_code=201,
    summary="An outside AI client (the MCP server) suggests a change; a person decides",
    description="Only a token issued to an allow-listed application (default `crm-mcp`) may call "
    "this, only while an administrator has switched the `mcp_client` agent on. The proposal "
    "waits in the same queue as every other; nothing changes until a different person approves "
    "it in the CRM. The organisation and the person come from the token, never from the body.",
    responses=problem_responses(401, 403, 404, 422, 429, 503),
)
def propose_external(
    data: ExternalProposal,
    principal: Proposer,
    session: Db,
    request: Request,
    token: Annotated[VerifiedToken, Depends(get_verified_token)],
) -> AgentActionRead:
    settings: Settings = request.app.state.settings
    allowed = frozenset(
        name.strip() for name in settings.external_proposal_clients.split(",") if name.strip()
    )
    azp = token.claims.get("azp")
    try:
        action = service.propose_external(
            session,
            principal,
            client_id=azp if isinstance(azp, str) else None,
            allowed_clients=allowed,
            agent_limits=agents_api.Limits.from_settings(settings),
            per_hour=settings.mcp_proposals_per_hour,
            kind=data.kind,
            target_type=data.target_type,
            target_id=data.target_id,
            payload=data.payload,
            reason=data.reason,
            expires_in_days=settings.agent_action_expiry_days,
            pending_limit=settings.agent_action_pending_per_user,
            sentinel_limits=sentinel.Limits.from_settings(settings),
        )
    except service.ProposalBlockedError as blocked:
        # The refusal is recorded (rule codes and ids only) even though nothing was stored.
        service.audit_blocked(session, principal, blocked)
        session.commit()
        raise
    session.commit()
    return _read(session, principal, action)


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
