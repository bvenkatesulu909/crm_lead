"""The approval queue for AI-proposed actions (ADR 0014, step AP1).

    AI (for a signed-in staff member) ─► propose: catalogue kind, valid payload, record visible
        ─► pending ─► a DIFFERENT person with agent_action:approve decides
            approve: lock, still pending / same version / not expired, approver sees the record,
                     run through the owning module's api.py AS THE APPROVER (savepoint)
                     ─► approved, or failed (nothing changed) ─► audit
            reject:  note required ─► rejected ─► audit

The service never commits; the router (step AP2) commits once.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.errors import ConflictError, DomainError, ForbiddenError, NotFoundError
from app.core.events import publish
from app.core.observability.metrics import AI_SENTINEL_FINDINGS
from app.modules.accounts import api as accounts_api
from app.modules.agents import api as agents_api
from app.modules.approvals import artifact, repository, sentinel
from app.modules.approvals.catalogue import KINDS, ActionKind, Proposal, Ran
from app.modules.approvals.models import AGENTS, REASON_MAX, AgentAction
from app.modules.contacts import api as contacts_api
from app.modules.identity import api as identity_api
from app.modules.leads import api as leads_api

ENTITY = "agent_action"
logger = logging.getLogger(__name__)
DEFAULT_EXPIRY_DAYS = 7
DEFAULT_PENDING_LIMIT = 20


class UnknownActionError(DomainError):
    status_code = 422
    code = "unknown_agent_action"


class InvalidActionError(DomainError):
    status_code = 422
    code = "invalid_agent_action"


class ProposalBlockedError(DomainError):
    """The Sentinel (ADR 0017) refused the proposal. Nothing was stored. The reasons are plain
    sentences that never repeat the text that was found."""

    status_code = 422
    code = "proposal_blocked"

    def __init__(
        self,
        findings: list[sentinel.Finding],
        *,
        kind: str,
        target_type: str,
        target_id: uuid.UUID,
        requester_id: uuid.UUID,
        agent: str,
    ) -> None:
        self.codes = [f.code for f in findings]
        self.kind, self.target_type, self.target_id = kind, target_type, target_id
        self.requester_id, self.agent = requester_id, agent
        self.action_id = uuid.uuid4()  # the id the proposal would have had (for the audit entry)
        super().__init__("The proposal was not accepted. " + " ".join(f.message for f in findings))


class RecheckFailedError(DomainError):
    status_code = 409
    code = "agent_action_recheck_failed"


class LimitReachedError(DomainError):
    status_code = 429
    code = "agent_action_limit_reached"

    def __init__(self) -> None:
        super().__init__("Too many proposals are waiting for a decision. Please wait for them.")


class ExternalClientNotAllowedError(ForbiddenError):
    code = "external_client_not_allowed"

    def __init__(self) -> None:
        super().__init__("This application may not create proposals.")


class ExternalProposalLimitError(DomainError):
    status_code = 429
    code = "mcp_proposal_limit_reached"

    def __init__(self) -> None:
        super().__init__("You have made enough proposals through AI clients this hour.")


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


def _publish(session: Session, action: AgentAction, name: str, *, actor: uuid.UUID | None) -> None:
    data = {"action_id": str(action.id)}
    if actor is not None:
        data["actor_id"] = str(actor)
    publish(session, action.tenant_id, name, data)


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
            **({"via_client": action.via_client} if action.via_client else {}),
            "status": action.status,
            "result": action.result,
        },
    )


# --- the Sentinel (ADR 0017) ---------------------------------------------------------------


def sentinel_facts(
    session: Session,
    principal: Principal,
    *,
    kind: str,
    target_type: str,
    target_id: uuid.UUID,
    payload: dict[str, Any],
    now: datetime | None = None,
) -> sentinel.Facts:
    """What the database says about the record and the asker, for the rules."""
    tenant_id, user_id = _staff(principal, Permission.AGENT_ACTION_PROPOSE)
    moment = now or _now()
    status: str | None = None
    owner: uuid.UUID | None = None
    texts: list[str] = []
    record_tenant = tenant_id  # an account or contact: the visibility check already ran
    if target_type == "lead":
        snapshot = leads_api.lead_snapshot(session, principal, target_id)
        if snapshot is None:
            raise RecordNotFoundError()
        record_tenant, status, owner, texts = (
            snapshot.tenant_id,
            snapshot.status,
            snapshot.owner_id,
            snapshot.texts,
        )
    assignee_tenant: uuid.UUID | None = None
    person = payload.get("owner_id") or payload.get("assignee_id")
    if person:
        try:
            known = identity_api.is_active_staff_member(session, tenant_id, uuid.UUID(str(person)))
        except ValueError:
            known = False
        # A person who is not an active colleague here belongs to "no known organisation".
        assignee_tenant = tenant_id if known else uuid.UUID(int=0)
    hour, day = moment - timedelta(hours=1), moment - timedelta(days=1)
    return sentinel.Facts(
        record_tenant_id=record_tenant,
        assignee_tenant_id=assignee_tenant,
        lead_status=status,
        lead_owner_id=owner,
        proposals_last_hour=repository.count_since(
            session, tenant_id, since=hour, requester=user_id
        ),
        assignments_last_hour=repository.count_since(
            session, tenant_id, since=hour, requester=user_id, kind="lead.assign"
        ),
        same_record_today=repository.count_since(
            session, tenant_id, since=day, target_id=target_id
        ),
        identical_pending=repository.identical_pending(
            session, tenant_id, kind=kind, target_id=target_id, payload=payload
        ),
        record_texts=texts,
    )


def _observe(verdict: sentinel.Verdict) -> None:
    for finding in verdict.findings:
        AI_SENTINEL_FINDINGS.labels(rule=finding.code, severity=finding.severity).inc()


def audit_blocked(session: Session, principal: Principal, error: ProposalBlockedError) -> None:
    """Write the audit entry of a refused proposal. Called by the caller AFTER it has rolled
    back its savepoint, so the entry survives: it holds rule codes and ids, never text."""
    record_audit(
        session,
        principal,
        action="agent_action.blocked",
        entity_type=ENTITY,
        entity_id=error.action_id,
        changes={
            "kind": error.kind,
            "target_type": error.target_type,
            "target_id": str(error.target_id),
            "requested_by": str(error.requester_id),
            "agent": error.agent,
            "codes": error.codes,
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
    pending_limit: int = DEFAULT_PENDING_LIMIT,
    sentinel_limits: sentinel.Limits | None = None,
    via_client: str | None = None,
) -> AgentAction:
    """Store a pending proposal. Nothing in the CRM changes until someone else approves it."""
    tenant_id, user_id = _staff(principal, Permission.AGENT_ACTION_PROPOSE)
    action_kind = _kind(kind)
    target = target_type or action_kind.target_types[0]
    if target not in action_kind.target_types:
        raise InvalidActionError(f"'{kind}' can't be proposed for a {target}.")
    if agent not in AGENTS:
        raise InvalidActionError("Unknown AI feature.")
    if (agent == "mcp_client") != (via_client is not None):
        raise InvalidActionError("A proposal through a client must name it.")
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
    if repository.pending_count(session, tenant_id, user_id) >= pending_limit:
        raise LimitReachedError()

    # The second, rule-based check (ADR 0017). It fails closed: a rule that cannot be
    # evaluated refuses the proposal.
    stored_payload = data.model_dump(mode="json", exclude_none=True)
    candidate = sentinel.Candidate(kind, why, stored_payload, user_id, tenant_id)
    verdict = sentinel.verify(
        candidate,
        sentinel_facts(
            session,
            principal,
            kind=kind,
            target_type=target,
            target_id=target_id,
            payload=stored_payload,
        ),
        sentinel_limits or sentinel.Limits.default(),
    )
    _observe(verdict)
    if verdict.blocked:
        raise ProposalBlockedError(
            verdict.blocks,
            kind=kind,
            target_type=target,
            target_id=target_id,
            requester_id=user_id,
            agent=agent,
        )

    # The plan (ADR 0018): what will change, judged against the record as it is now. A plan that
    # cannot be prepared refuses the proposal: an approver must never decide without one.
    try:
        plan = action_kind.spec(session, principal, proposal, data)
    except Exception as error:  # noqa: BLE001 - fail closed, whatever went wrong
        logger.error("preparing the plan of a %s proposal failed (%s)", kind, type(error).__name__)
        raise ProposalBlockedError(
            [
                sentinel.Finding(
                    "artifact_error",
                    "block",
                    "The plan for this proposal could not be prepared, so it was not accepted.",
                )
            ],
            kind=kind,
            target_type=target,
            target_id=target_id,
            requester_id=user_id,
            agent=agent,
        ) from None

    action = AgentAction(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        kind=kind,
        target_type=target,
        target_id=target_id,
        payload=stored_payload,
        verification=artifact.build_artifact(verdict, plan.changes, plan.basis),
        reason=why,
        agent=agent,
        via_client=via_client,
        requested_by_user_id=user_id,
        status="pending",
        expires_at=_now() + timedelta(days=expires_in_days),
    )
    session.add(action)
    session.flush()
    _audit(session, principal, action, "proposed")
    # Approvers are told by the worker (notifications); the requester isn't (actor).
    _publish(session, action, "agent_action.proposed", actor=user_id)
    return action


MCP_AGENT = "mcp_client"


def propose_external(
    session: Session,
    principal: Principal,
    *,
    client_id: str | None,
    allowed_clients: frozenset[str],
    agent_limits: agents_api.Limits,
    per_hour: int,
    kind: str,
    target_type: str | None,
    target_id: uuid.UUID,
    payload: Any,
    reason: str,
    expires_in_days: int = DEFAULT_EXPIRY_DAYS,
    pending_limit: int = DEFAULT_PENDING_LIMIT,
    sentinel_limits: sentinel.Limits | None = None,
) -> AgentAction:
    """A proposal from an outside AI client (ADR 0020): the same queue and the same rules as
    every other proposal, behind three more locks - only a VERIFIED allow-listed application,
    the organisation's switch (off until an administrator turns it on) and a lower hourly
    ceiling for this person."""
    # The client name comes from the verified token, never from the request body.
    if client_id is None or client_id not in allowed_clients:
        raise ExternalClientNotAllowedError()
    tenant_id, user_id = _staff(principal, Permission.AGENT_ACTION_PROPOSE)
    now = _now()
    try:
        agents_api.check_can_call(session, tenant_id, MCP_AGENT, agent_limits, now)
    except agents_api.AgentUnavailableError:
        raise  # a plain 503: the switch is the organisation's, or the platform's, to flip
    since = now - timedelta(hours=1)
    made = repository.count_since(
        session, tenant_id, since=since, requester=user_id, agent=MCP_AGENT
    )
    if made >= per_hour:
        raise ExternalProposalLimitError()
    action = propose(
        session,
        principal,
        kind=kind,
        target_type=target_type,
        target_id=target_id,
        payload=payload,
        reason=reason,
        agent=MCP_AGENT,
        via_client=client_id,
        expires_in_days=expires_in_days,
        pending_limit=pending_limit,
        sentinel_limits=sentinel_limits,
    )
    # Counted as one call, so the registry page shows how often the switch is used.
    agents_api.record_usage(
        session, tenant_id, MCP_AGENT, input_tokens=0, output_tokens=0, limits=agent_limits, now=now
    )
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
    # The requester is told by the worker; the decider isn't (actor).
    _publish(session, action, "agent_action.decided", actor=user_id)


def _recheck(session: Session, principal: Principal, action: AgentAction) -> None:
    """Judge the record's state again at approval (ADR 0017, S4): a lead converted or changed
    while the proposal waited must not be acted on with stale facts."""
    candidate = sentinel.Candidate(
        action.kind,
        action.reason,
        dict(action.payload),
        action.requested_by_user_id,
        action.tenant_id,
    )
    facts = sentinel_facts(
        session,
        principal,
        kind=action.kind,
        target_type=action.target_type,
        target_id=action.target_id,
        payload=candidate.payload,
    )
    verdict = sentinel.verify(candidate, facts, sentinel.Limits.default(), recheck=True)
    _observe(verdict)
    if verdict.blocked:
        raise RecheckFailedError(" ".join(f.message for f in verdict.blocks))


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
    ran: Ran | None = None
    try:
        with session.begin_nested():
            _recheck(session, principal, action)
            ran = kind.run(session, principal, _proposal(action), data)
            action.result = ran.text[:REASON_MAX]
    except DomainError as exc:
        status = "failed"
        ran = None
        action.result = exc.detail[:REASON_MAX]
    seen: list[artifact.Change] | None = None
    if ran is not None:
        try:
            seen = kind.observe(session, principal, _proposal(action), data, ran)
        except Exception as error:  # noqa: BLE001 - the action ran; say we could not look
            logger.error("observing a %s outcome failed (%s)", action.kind, type(error).__name__)
            seen = []
    _write_outcome(session, principal, action, user_id, seen)
    _decide(session, action, user_id, status, (note or "").strip()[:REASON_MAX] or None)
    _audit(session, principal, action, status)
    return action


def _planned(action: AgentAction) -> list[artifact.Change] | None:
    """The plan stored with the proposal, or None for one made before artifacts existed."""
    spec = (action.verification or {}).get("spec")
    if not isinstance(spec, dict):
        return None
    return [
        artifact.Change(item["field"], item.get("before"), item.get("after"))
        for item in spec.get("changes", [])
    ]


def _write_outcome(
    session: Session,
    principal: Principal,
    action: AgentAction,
    approver_id: uuid.UUID,
    seen: list[artifact.Change] | None,
) -> None:
    """Add what was seen after the action to the artifact (a new dict, so the change is saved)
    and record a difference between the plan and what happened."""
    outcome = artifact.outcome_json(approver_id, _planned(action), seen)
    action.verification = {**(action.verification or {}), "outcome": outcome}
    if outcome["matches_spec"] is False:
        record_audit(
            session,
            principal,
            action="agent_action.mismatch",
            entity_type=ENTITY,
            entity_id=action.id,
            changes={
                "kind": action.kind,
                "target_type": action.target_type,
                "target_id": str(action.target_id),
                "differs": outcome["differs"],
            },
        )


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


def list_actions(
    session: Session,
    principal: Principal,
    *,
    status: str | None,
    mine: bool,
    target_id: uuid.UUID | None = None,
    limit: int,
    offset: int,
) -> tuple[list[AgentAction], int]:
    """Approvers: the organisation's proposals (or only their own with ``mine``); everyone
    else: their own. Filtered in SQL, newest first."""
    approver = principal.has_permission(Permission.AGENT_ACTION_APPROVE)
    tenant_id, user_id = _staff(
        principal, Permission.AGENT_ACTION_APPROVE if approver else Permission.AGENT_ACTION_PROPOSE
    )
    requester = user_id if mine or not approver else None
    return repository.page(
        session,
        tenant_id,
        status=status,
        requester=requester,
        target_id=target_id,
        limit=limit,
        offset=offset,
    )


def target_link(action: AgentAction) -> str:
    return f"/{action.target_type}s/{action.target_id}"


def target_label(session: Session, principal: Principal, action: AgentAction) -> str | None:
    """The record's name - only if this person may see the record (else None)."""
    if not _visible(session, principal, action.target_type, action.target_id):
        return None
    if action.target_type == "lead":
        return leads_api.lead_brief(session, principal, action.target_id)
    if action.target_type == "account":
        return accounts_api.account_name(session, action.tenant_id, action.target_id)
    return contacts_api.contact_name(session, action.tenant_id, action.target_id)


def action_brief(
    session: Session, principal: Principal, action_id: uuid.UUID
) -> tuple[str, str, str] | None:
    """(status, description, link) of a proposal this person may read, else None - for
    notifications."""
    try:
        action = get_action(session, principal, action_id)
    except DomainError:
        return None
    return action.status, describe(action), f"/approvals/{action.id}"


# --- worker: expiry (step AP2) --------------------------------------------------------------


def expire_due(session: Session, now: datetime, *, tenant_id: uuid.UUID) -> int:
    """Mark pending proposals whose time is up as expired and tell their requesters. Safe to
    run twice: an expired proposal is no longer pending."""
    expired = repository.due_for_expiry(session, tenant_id, now)
    for action in expired:
        action.status = "expired"
        action.decided_at = now
    session.flush()
    for action in expired:
        _publish(session, action, "agent_action.decided", actor=None)
    return len(expired)


def requester_of(session: Session, tenant_id: uuid.UUID, action_id: uuid.UUID) -> uuid.UUID | None:
    """Who asked for the proposal (for notifications; they are still checked: may they read it?)."""
    action = repository.get(session, tenant_id, action_id)
    return action.requested_by_user_id if action else None
