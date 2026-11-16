"""Running a custom agent on one record, and trying it first (ADR 0034, AB2b).

    permission ─► the agent (not archived) ─► its current version was tried ─► the record (only if
    the asker may read it) ─► limits ─► governed model (switch, budget) ─► strict check of its ONE
    tool call ─► at most one proposal ─► one insert-only run record + audit

The model sees one record and the administrator's written instruction; it can call one tool that
only reports what it suggests. This file turns that into a proposal for the approval queue (never
a change), through the approvals module and its Sentinel. The model is always wrapped by the agent
registry (ADR 0016). A dry run (``try_agent``, administrators only) does everything except create
the proposal, and a successful one is what lets an agent be switched on. Services never commit.

This file imports the agents and approvals modules, so ``api.py`` does not import it: the agent
registry imports ``api.py`` and the two would otherwise import each other.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.config import Settings
from app.core.errors import ConflictError, DomainError, ForbiddenError, NotFoundError
from app.modules.agents import api as agents_api
from app.modules.approvals import api as approvals_api
from app.modules.approvals.models import AgentAction
from app.modules.assistant.api import ChatModel
from app.modules.custom_agents import facts, repository, rules, run_rules
from app.modules.custom_agents.models import CustomAgent, CustomAgentRun, CustomAgentVersion
from app.modules.custom_agents.service import CustomAgentNotFoundError

ASK = "Read the record and call submit_suggestion once."


class RecordNotFoundError(NotFoundError):
    code = "custom_agent_record_not_found"

    def __init__(self) -> None:
        # The same answer whether the record does not exist, is another organisation's or is not
        # one the asker may read.
        super().__init__("Record not found.")


class NeedsTrialError(ConflictError):
    code = "custom_agent_needs_trial"

    def __init__(self) -> None:
        super().__init__(
            "This version of the agent has not been tried yet. Ask an administrator to run a "
            "dry run first."
        )


class AnswerInvalidError(DomainError):
    status_code = 422
    code = "custom_agent_answer_invalid"


class RateLimitedError(DomainError):
    status_code = 429
    code = "custom_agent_rate_limited"


@dataclass(frozen=True)
class Limits:
    """How often custom agents may run (settings ``CRM_CUSTOM_AGENT_PER_*``). The platform sets
    them; a definition cannot raise them."""

    per_record_hour: int
    per_user_hour: int
    per_tenant_day: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "Limits":
        return cls(
            settings.custom_agent_per_record_hour,
            settings.custom_agent_per_user_hour,
            settings.custom_agent_per_tenant_day,
        )

    @classmethod
    def default(cls) -> "Limits":
        fields = Settings.model_fields
        return cls(
            int(fields["custom_agent_per_record_hour"].default),
            int(fields["custom_agent_per_user_hour"].default),
            int(fields["custom_agent_per_tenant_day"].default),
        )


@dataclass(frozen=True)
class RunResult:
    run: CustomAgentRun
    proposal: AgentAction | None
    # Why the approvals module refused the proposal (the Sentinel), if it did.
    blocked_message: str | None = None


@dataclass(frozen=True)
class TrialResult:
    """What the agent WOULD do; nothing was proposed."""

    run: CustomAgentRun
    suggestion: run_rules.Suggestion
    planned: run_rules.Planned | None
    sets_shown: list[str]


@dataclass(frozen=True)
class _Prepared:
    agent: CustomAgent
    version: CustomAgentVersion
    record_type: str
    view: facts.RecordView
    kinds: list[str]


def _tenant(principal: Principal, permission: Permission) -> uuid.UUID:
    if (
        principal.tenant_id is None
        or principal.user_id is None
        or principal.user_type != "staff"
        or not principal.has_permission(permission)
    ):
        raise ForbiddenError("You may not do this.")
    return principal.tenant_id


def _user(principal: Principal) -> uuid.UUID:
    if principal.user_id is None:  # _tenant already refused a principal without one
        raise ForbiddenError("You may not do this.")
    return principal.user_id


def _check_limits(
    session: Session,
    principal: Principal,
    tenant_id: uuid.UUID,
    record_id: uuid.UUID,
    limits: Limits,
    now: datetime,
) -> None:
    hour, day = now - timedelta(hours=1), now - timedelta(days=1)
    if (
        repository.count_runs(session, tenant_id, since=hour, record_id=record_id, real_only=True)
        >= limits.per_record_hour
    ):
        raise RateLimitedError("This record was handled by a custom agent a moment ago.")
    if (
        repository.count_runs(session, tenant_id, since=hour, user_id=principal.user_id)
        >= limits.per_user_hour
    ):
        raise RateLimitedError("You have run many agents. Try again later.")
    if repository.count_runs(session, tenant_id, since=day) >= limits.per_tenant_day:
        raise RateLimitedError("Your organisation reached its daily limit for custom agents.")


def _prepare(
    session: Session,
    principal: Principal,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    record_id: uuid.UUID,
    *,
    need_trial: bool,
) -> _Prepared:
    agent = repository.get(session, tenant_id, agent_id)
    if agent is None or agent.archived_at is not None:
        raise CustomAgentNotFoundError()
    version = repository.get_version(session, tenant_id, agent.id, agent.current_version)
    if version is None:  # cannot happen: the two are written together
        raise CustomAgentNotFoundError()
    if need_trial and not repository.has_trial(session, tenant_id, agent.id, version.version_no):
        raise NeedsTrialError()
    record_type = rules.RECORD_TYPE_OF[version.read_sets[0]]
    view = facts.load(session, principal, record_type, record_id, list(version.read_sets))
    if view is None:
        raise RecordNotFoundError()
    return _Prepared(agent, version, record_type, view, list(version.suggestion_kinds))


def _governed(
    session: Session,
    model: ChatModel,
    tenant_id: uuid.UUID,
    key: str,
    ai_limits: agents_api.Limits | None,
    *,
    trial: bool,
) -> ChatModel:
    """The registry gate (ADR 0016): off, over budget or the tool taken away stops it here. A dry
    run may call while the agent is still switched off; the budget and platform switch apply."""
    governed: ChatModel = agents_api.governed(
        model, session, tenant_id, key, ai_limits or agents_api.Limits.default(), trial=trial
    )
    if not governed.available:
        governed.reply(system="", messages=[], tools=[])  # raises "not configured"
    return governed


def _ask(governed: ChatModel, prepared: _Prepared) -> run_rules.Suggestion:
    """One call of the (governed) model and the strict check of its one tool call."""
    reply = governed.reply(
        system=run_rules.system_prompt(
            purpose=prepared.version.purpose,
            instruction=prepared.version.instruction,
            record_type=prepared.record_type,
            shown=prepared.view.shown,
            suspicious=prepared.view.suspicious,
            kinds=prepared.kinds,
        ),
        messages=[{"role": "user", "content": ASK}],
        tools=[run_rules.submit_tool(prepared.kinds)],
    )
    uses = reply.tool_uses
    if len(uses) != 1 or uses[0].name != run_rules.TOOL_NAME:
        raise AnswerInvalidError("The agent did not return exactly one suggestion.")
    try:
        return run_rules.parse_suggestion(uses[0].input, prepared.kinds)
    except run_rules.SuggestionRefused as refusal:
        raise AnswerInvalidError(str(refusal)) from None


def _plan(prepared: _Prepared, suggestion: run_rules.Suggestion) -> run_rules.Planned | None:
    owner = prepared.view.owner_id
    return run_rules.plan(
        suggestion,
        record_type=prepared.record_type,
        current_status=prepared.view.status,
        owner_id=str(owner) if owner else None,
        agent_name=prepared.agent.name,
        version=prepared.version.version_no,
    )


def _record(
    session: Session,
    principal: Principal,
    prepared: _Prepared,
    record_id: uuid.UUID,
    *,
    mode: str,
    suggestion: run_rules.Suggestion,
    outcome: str,
    proposal: AgentAction | None,
) -> CustomAgentRun:
    run = repository.add_run(
        session,
        CustomAgentRun(
            tenant_id=prepared.agent.tenant_id,
            custom_agent_id=prepared.agent.id,
            version_no=prepared.version.version_no,
            mode=mode,
            record_type=prepared.record_type,
            record_id=record_id,
            user_id=_user(principal),
            action=suggestion.action,
            outcome=outcome,
            proposal_id=proposal.id if proposal else None,
        ),
    )
    # Ids and codes only - not the reason, which is text a model wrote.
    record_audit(
        session,
        principal,
        action="custom_agent.ran" if mode == "run" else "custom_agent.dry_run",
        entity_type="custom_agent",
        entity_id=prepared.agent.id,
        changes={
            "run_id": str(run.id),
            "version_no": prepared.version.version_no,
            "record_type": prepared.record_type,
            "record_id": str(record_id),
            "sets_shown": prepared.view.sets_shown,
            "action": suggestion.action,
            "outcome": outcome,
            "proposal_id": str(proposal.id) if proposal else None,
        },
    )
    return run


def run_agent(
    session: Session,
    principal: Principal,
    model: ChatModel,
    agent_id: uuid.UUID,
    record_id: uuid.UUID,
    *,
    limits: Limits | None = None,
    ai_limits: agents_api.Limits | None = None,
    now: datetime | None = None,
) -> RunResult:
    """Run an agent on one record as the person asking. The result is at most one pending proposal
    for someone else to approve."""
    tenant_id = _tenant(principal, Permission.CUSTOM_AGENT_RUN)
    when = now or datetime.now(UTC)
    prepared = _prepare(session, principal, tenant_id, agent_id, record_id, need_trial=True)
    _check_limits(session, principal, tenant_id, record_id, limits or Limits.default(), when)
    governed = _governed(
        session, model, tenant_id, prepared.agent.agent_key, ai_limits, trial=False
    )
    suggestion = _ask(governed, prepared)

    planned = _plan(prepared, suggestion)
    proposal: AgentAction | None = None
    blocked: str | None = None
    if planned is not None:
        try:
            # A savepoint: a refused proposal leaves nothing behind.
            with session.begin_nested():
                proposal = approvals_api.propose(
                    session,
                    principal,
                    kind=planned.kind,
                    target_type=planned.target_type,
                    target_id=record_id,
                    payload=planned.payload,
                    reason=planned.reason,
                    agent="custom_agent",
                    custom_agent_key=prepared.agent.agent_key,
                )
        except approvals_api.ProposalBlockedError as refusal:
            # Outside the savepoint, so the audit entry of the refusal stays with the request.
            approvals_api.audit_blocked(session, principal, refusal)
            blocked = refusal.detail
    outcome = "proposed" if proposal else ("blocked" if blocked else "no_proposal")
    run = _record(
        session,
        principal,
        prepared,
        record_id,
        mode="run",
        suggestion=suggestion,
        outcome=outcome,
        proposal=proposal,
    )
    return RunResult(run, proposal, blocked)


def try_agent(
    session: Session,
    principal: Principal,
    model: ChatModel,
    agent_id: uuid.UUID,
    record_id: uuid.UUID,
    *,
    limits: Limits | None = None,
    ai_limits: agents_api.Limits | None = None,
    now: datetime | None = None,
) -> TrialResult:
    """A dry run, for an administrator: the same call on one real record the administrator may
    read, but no proposal. The model call still goes through the registry (platform switch, token
    budget) even while the agent is switched off. A valid answer counts as the trial of this
    version of the agent."""
    tenant_id = _tenant(principal, Permission.CUSTOM_AGENT_MANAGE)
    when = now or datetime.now(UTC)
    prepared = _prepare(session, principal, tenant_id, agent_id, record_id, need_trial=False)
    _check_limits(session, principal, tenant_id, record_id, limits or Limits.default(), when)
    governed = _governed(session, model, tenant_id, prepared.agent.agent_key, ai_limits, trial=True)
    suggestion = _ask(governed, prepared)
    planned = _plan(prepared, suggestion)
    run = _record(
        session,
        principal,
        prepared,
        record_id,
        mode="trial",
        suggestion=suggestion,
        outcome="shown",
        proposal=None,
    )
    return TrialResult(run, suggestion, planned, prepared.view.sets_shown)
