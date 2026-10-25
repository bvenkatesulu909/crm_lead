"""The approval queue for AI-proposed actions (ADR 0014, step AP1).

    AI (for a signed-in staff member) ─► propose: catalogue kind, valid payload, record visible
        ─► pending ─► a DIFFERENT person with agent_action:approve decides
            approve: lock, still pending / same version / not expired, approver sees the record,
                     run through the owning module's api.py AS THE APPROVER (savepoint)
                     ─► approved, or failed (nothing changed) ─► audit
            reject:  note required ─► rejected ─► audit

The service never commits; the router (step AP2) commits once.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.errors import ConflictError, DomainError, ForbiddenError, NotFoundError
from app.modules.accounts import api as accounts_api
from app.modules.approvals import repository
from app.modules.approvals.catalogue import KINDS, ActionKind, Proposal
from app.modules.approvals.models import AGENTS, REASON_MAX, AgentAction
from app.modules.contacts import api as contacts_api
from app.modules.leads import api as leads_api

ENTITY = "agent_action"
DEFAULT_EXPIRY_DAYS = 7


class UnknownActionError(DomainError):
    status_code = 422
    code = "unknown_agent_action"


class InvalidActionError(DomainError):
    status_code = 422
    code = "invalid_agent_action"


class NoteRequiredError(DomainError):
    status_code = 422
    code = "decision_note_required"

    def __init__(self) -> None:
        super().__init__("Please say why the proposal is rejected.")


class AgentActionNotFoundError(NotFoundError):
    code = "agent_action_not_found"

    def __init__(self) -> None:
        super().__init__("The proposal doesn't exist.")


class RecordNotFoundError(NotFoundError):
    code = "record_not_found"

    def __init__(self) -> None:
        # Same answer whether the record doesn't exist, is another tenant's or isn't yours.
        super().__init__("The record doesn't exist.")


class SelfApprovalError(ForbiddenError):
    code = "self_approval_forbidden"

    def __init__(self) -> None:
        super().__init__("You can't decide on a proposal you asked for.")


class AlreadyDecidedError(ConflictError):
    code = "agent_action_already_decided"

    def __init__(self) -> None:
        super().__init__("This proposal was already decided.")


class ChangedError(ConflictError):
    code = "agent_action_changed"

    def __init__(self) -> None:
        super().__init__("The proposal changed in the meantime. Please reload it.")


class ExpiredError(ConflictError):
    code = "agent_action_expired"

    def __init__(self) -> None:
        super().__init__("This proposal has expired.")


def _now() -> datetime:
    return datetime.now(UTC)


def _staff(principal: Principal, permission: Permission) -> tuple[uuid.UUID, uuid.UUID]:
    if (
        principal.tenant_id is None
        or principal.user_id is None
        or principal.user_type != "staff"
        or not principal.has_permission(permission)
    ):
        raise ForbiddenError("You may not do this.")
    return principal.tenant_id, principal.user_id


def _visible(
    session: Session, principal: Principal, target_type: str, target_id: uuid.UUID
) -> bool:
    """Asked of the module that owns the record, under ITS read rules."""
    if target_type == "lead":
        return leads_api.is_readable_lead(session, principal, target_id)
    if target_type == "account":
        return accounts_api.is_readable_account(session, principal, target_id)
    if target_type == "contact":
        return contacts_api.is_readable_contact(session, principal, target_id)
    return False


def _kind(name: str) -> ActionKind:
    kind = KINDS.get(name)
    if kind is None:
        raise UnknownActionError(f"'{name}' is not an action that can be proposed.")
    return kind


def _payload(kind: ActionKind, payload: Any) -> Any:
    try:
        return kind.payload.model_validate(payload)
    except ValidationError as exc:
        # Field names and messages only, never the values (they came from a model).
        problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        raise InvalidActionError(f"The proposal is not valid ({problems}).") from exc


def _proposal(action: AgentAction) -> Proposal:
    return Proposal(
        tenant_id=action.tenant_id,
        target_type=action.target_type,
        target_id=action.target_id,
        requested_by_user_id=action.requested_by_user_id,
        reason=action.reason,
    )


def _audit(session: Session, principal: Principal, action: AgentAction, what: str) -> None:
    record_audit(
        session,
        principal,
        action=f"agent_action.{what}",
        entity_type=ENTITY,
        entity_id=action.id,
        changes={
            "kind": action.kind,
            "target_type": action.target_type,
            "target_id": str(action.target_id),
            "requested_by": str(action.requested_by_user_id),
            "agent": action.agent,
            "status": action.status,
            "result": action.result,
        },
    )


# --- proposing -------------------------------------------------------------------------------


def propose(
    session: Session,
    principal: Principal,
    *,
    kind: str,
    target_id: uuid.UUID,
    payload: Any,
    reason: str,
    agent: str,
    target_type: str | None = None,
    expires_in_days: int = DEFAULT_EXPIRY_DAYS,
) -> AgentAction:
    """Store a pending proposal. Nothing in the CRM changes until someone else approves it."""
    tenant_id, user_id = _staff(principal, Permission.AGENT_ACTION_PROPOSE)
    action_kind = _kind(kind)
    target = target_type or action_kind.target_types[0]
    if target not in action_kind.target_types:
        raise InvalidActionError(f"'{kind}' can't be proposed for a {target}.")
    if agent not in AGENTS:
        raise InvalidActionError("Unknown AI feature.")
    why = (reason or "").strip()
    if not why or len(why) > REASON_MAX:
        raise InvalidActionError(f"reason: 1 to {REASON_MAX} characters are required.")
    data = _payload(action_kind, payload)
    if not _visible(session, principal, target, target_id):
        raise RecordNotFoundError()
    proposal = Proposal(tenant_id, target, target_id, user_id, why)
    problem = action_kind.check(session, proposal, data)
    if problem:
        raise InvalidActionError(f"The proposal is not valid ({problem}).")

    action = AgentAction(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        kind=kind,
        target_type=target,
        target_id=target_id,
        payload=data.model_dump(mode="json", exclude_none=True),
        reason=why,
        agent=agent,
        requested_by_user_id=user_id,
        status="pending",
        expires_at=_now() + timedelta(days=expires_in_days),
    )
    session.add(action)
    session.flush()
    _audit(session, principal, action, "proposed")
    return action


def describe(action: AgentAction) -> str:
    """One line for the approver, e.g. "Change the lead's status to qualified"."""
    kind = KINDS.get(action.kind)
    if kind is None:
        return action.kind
    try:
        return kind.describe(kind.payload.model_validate(action.payload))
    except ValidationError:
        return action.kind


# --- reading --------------------------------------------------------------------------------


def get_action(session: Session, principal: Principal, action_id: uuid.UUID) -> AgentAction:
    """Approvers read every proposal of the organisation; others only their own."""
    if principal.has_permission(Permission.AGENT_ACTION_APPROVE):
        tenant_id, user_id = _staff(principal, Permission.AGENT_ACTION_APPROVE)
    else:
        tenant_id, user_id = _staff(principal, Permission.AGENT_ACTION_PROPOSE)
    action = repository.get(session, tenant_id, action_id)
    if action is None or (
        not principal.has_permission(Permission.AGENT_ACTION_APPROVE)
        and action.requested_by_user_id != user_id
    ):
        raise AgentActionNotFoundError()
    return action


# --- deciding -------------------------------------------------------------------------------


def _decidable(
    session: Session, principal: Principal, action_id: uuid.UUID, version: int
) -> tuple[AgentAction, uuid.UUID]:
    tenant_id, user_id = _staff(principal, Permission.AGENT_ACTION_APPROVE)
    action = repository.lock(session, tenant_id, action_id)
    if action is None:
        raise AgentActionNotFoundError()
    if action.requested_by_user_id == user_id:
        raise SelfApprovalError()
    if action.status != "pending":
        raise AlreadyDecidedError()
    if action.version != version:
        raise ChangedError()
    if action.expires_at <= _now():
        raise ExpiredError()  # the worker marks it expired (step AP2)
    return action, user_id


def _decide(
    session: Session, action: AgentAction, user_id: uuid.UUID, status: str, note: str | None
) -> None:
    action.status = status
    action.decided_by_user_id = user_id
    action.decided_at = _now()
    action.decision_note = note
    session.flush()


def approve(
    session: Session,
    principal: Principal,
    action_id: uuid.UUID,
    *,
    version: int,
    note: str | None = None,
) -> AgentAction:
    """Run the proposed action as the approver. If the owning module refuses it, nothing
    changes and the proposal is marked failed with the reason."""
    action, user_id = _decidable(session, principal, action_id, version)
    # The approver's own rights decide: a record they can't see doesn't exist for them.
    if not _visible(session, principal, action.target_type, action.target_id):
        raise RecordNotFoundError()
    kind = _kind(action.kind)
    data = _payload(kind, action.payload)  # checked again: the catalogue may have changed
    status = "approved"
    try:
        with session.begin_nested():
            action.result = kind.run(session, principal, _proposal(action), data)[:REASON_MAX]
    except DomainError as exc:
        status = "failed"
        action.result = exc.detail[:REASON_MAX]
    _decide(session, action, user_id, status, (note or "").strip()[:REASON_MAX] or None)
    _audit(session, principal, action, status)
    return action


def reject(
    session: Session, principal: Principal, action_id: uuid.UUID, *, version: int, note: str
) -> AgentAction:
    why = (note or "").strip()
    if not why:
        raise NoteRequiredError()
    action, user_id = _decidable(session, principal, action_id, version)
    _decide(session, action, user_id, "rejected", why[:REASON_MAX])
    _audit(session, principal, action, "rejected")
    return action
