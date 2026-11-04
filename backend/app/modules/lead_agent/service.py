"""Asking the lead agent to look at one lead (ADR 0022, step LA2).

    permission ─► limits ─► graph:
        read (only a lead the asker may read) ─► governed model (switch, budget, tool filter)
        ─► strict check ─► ONE proposal (approvals + Sentinel) ─► audit

It only ever PROPOSES: a different person approves in the approval queue. Services never commit.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog, record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.config import Settings
from app.core.errors import DomainError, ForbiddenError, NotFoundError
from app.core.records import LeadQualifierFacts
from app.modules.agents import api as agents_api
from app.modules.approvals import api as approvals_api
from app.modules.approvals.models import AgentAction
from app.modules.assistant.api import ChatModel
from app.modules.lead_agent import graph, rules
from app.modules.leads import api as leads_api

AGENT = "lead_agent"
AUDIT_ACTION = "lead_agent.ran"
ASK = "Look at this lead and call submit_suggestion once."


class LeadNotFoundError(NotFoundError):
    code = "lead_not_found"

    def __init__(self) -> None:
        # The same answer whether the lead does not exist, is another organisation's or is not
        # one the asker may read.
        super().__init__("Lead not found.")


class SuggestionInvalidError(DomainError):
    status_code = 422
    code = "lead_agent_invalid_answer"


class RateLimitedError(DomainError):
    status_code = 429
    code = "lead_agent_rate_limited"


@dataclass(frozen=True)
class Limits:
    """How often the agent may run (settings ``CRM_LEAD_AGENT_PER_*``)."""

    per_lead_hour: int
    per_tenant_day: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "Limits":
        return cls(settings.lead_agent_per_lead_hour, settings.lead_agent_per_tenant_day)

    @classmethod
    def default(cls) -> "Limits":
        fields = Settings.model_fields
        return cls(
            int(fields["lead_agent_per_lead_hour"].default),
            int(fields["lead_agent_per_tenant_day"].default),
        )


@dataclass(frozen=True)
class RunResult:
    outcome: str  # "proposed" | "no_suggestion" | "blocked"
    proposal: AgentAction | None
    blocked_message: str | None = None


def _count_runs(
    session: Session, tenant_id: uuid.UUID, since: datetime, lead_id: uuid.UUID | None = None
) -> int:
    query = select(func.count()).where(
        AuditLog.tenant_id == tenant_id,
        AuditLog.action == AUDIT_ACTION,
        AuditLog.occurred_at >= since,
    )
    if lead_id is not None:
        query = query.where(AuditLog.entity_id == lead_id)
    return int(session.scalar(query) or 0)


def _check_limits(
    session: Session, tenant_id: uuid.UUID, lead_id: uuid.UUID, limits: Limits, now: datetime
) -> None:
    if _count_runs(session, tenant_id, now - timedelta(hours=1), lead_id) >= limits.per_lead_hour:
        raise RateLimitedError("This lead was looked at a moment ago. Try again in an hour.")
    if _count_runs(session, tenant_id, now - timedelta(days=1)) >= limits.per_tenant_day:
        raise RateLimitedError("Your organisation reached its daily limit for the lead agent.")


def _governed(
    session: Session, model: ChatModel, tenant_id: uuid.UUID, ai_limits: agents_api.Limits | None
) -> ChatModel:
    """The registry gate (ADR 0016): off, over budget or the tool taken away stops it here."""
    governed: ChatModel = agents_api.governed(
        model, session, tenant_id, AGENT, ai_limits or agents_api.Limits.default()
    )
    if not governed.available:
        governed.reply(system="", messages=[], tools=[])  # raises "not configured"
    return governed


def run_lead_agent(
    session: Session,
    principal: Principal,
    model: ChatModel,
    lead_id: uuid.UUID,
    *,
    limits: Limits | None = None,
    ai_limits: agents_api.Limits | None = None,
    now: datetime | None = None,
) -> RunResult:
    if (
        principal.tenant_id is None
        or principal.user_id is None
        or principal.user_type != "staff"
        # The same people who may run the Qualifier may run the lead agent (ADR 0022).
        or not principal.has_permission(Permission.QUALIFIER_RUN)
    ):
        raise ForbiddenError("You may not do this.")
    tenant_id = principal.tenant_id
    when = now or datetime.now(UTC)
    _check_limits(session, tenant_id, lead_id, limits or Limits.default(), when)
    governed = _governed(session, model, tenant_id, ai_limits)
    blocked: list[str] = []

    def read() -> LeadQualifierFacts | None:
        return leads_api.qualifier_facts(session, principal, lead_id)

    def decide(facts: LeadQualifierFacts) -> graph.Plan | None:
        shown, _names, suspicious = rules.model_view(facts)
        reply = governed.reply(
            system=rules.system_prompt(shown, suspicious),
            messages=[{"role": "user", "content": ASK}],
            tools=[rules.submit_tool()],
        )
        try:
            suggestion = rules.parse(reply.tool_uses)
        except rules.SuggestionRefusedError as refusal:
            raise SuggestionInvalidError(str(refusal)) from None
        return rules.plan(suggestion, facts)

    def propose(plan: graph.Plan) -> AgentAction | None:
        try:
            # A savepoint: a refused proposal leaves nothing behind.
            with session.begin_nested():
                return approvals_api.propose(
                    session,
                    principal,
                    kind=plan.kind,
                    target_type=plan.target_type,
                    target_id=lead_id,
                    payload=plan.payload,
                    reason=plan.reason,
                    agent=AGENT,
                )
        except approvals_api.ProposalBlockedError as refusal:
            # Outside the savepoint, so the audit entry of the refusal stays with the request.
            approvals_api.audit_blocked(session, principal, refusal)
            blocked.append(refusal.detail)
            return None

    result = graph.run(graph.Ports(read, decide, propose))
    if result.outcome == "lead_not_found":
        raise LeadNotFoundError()
    outcome = "blocked" if blocked else result.outcome
    proposal: AgentAction | None = result.proposal
    # Ids and codes only - not the reason, which is text a model wrote.
    record_audit(
        session,
        principal,
        action=AUDIT_ACTION,
        entity_type="lead",
        entity_id=lead_id,
        changes={"outcome": outcome, "proposal_id": str(proposal.id) if proposal else None},
    )
    return RunResult(outcome, proposal, blocked[0] if blocked else None)
