"""Asking the Qualifier to assess one lead (docs/qualifier.md, QA2 and QA3).

    permission ─► active procedure ─► the lead (only if the asker may read it) ─► limits
        ─► governed model (switch, budget) ─► strict check of its ONE tool call
        ─► at most one proposal ─► one insert-only record + audit + metrics

The model sees one lead and the written steps; it can call one tool that only reports what it
thinks. This file turns that into a proposal for the approval queue (never a change), through
the approvals module and its Sentinel. The model is always wrapped by the agent registry (ADR
0016): an organisation can switch the Qualifier off or cap its tokens. Services never commit.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.config import Settings
from app.core.errors import DomainError, ForbiddenError, NotFoundError
from app.core.observability.metrics import QUALIFIER_ASSESSMENTS, QUALIFIER_REFUSALS
from app.core.screening import screen
from app.modules.agents import api as agents_api
from app.modules.approvals import api as approvals_api
from app.modules.approvals.models import AgentAction
from app.modules.assistant.api import ChatModel
from app.modules.leads import api as leads_api
from app.modules.qualifier import repository, rules
from app.modules.qualifier.models import LeadAssessment
from app.modules.qualifier.service import NoActiveProcedureError

AGENT = "qualifier"
ASK = "Assess this lead against the numbered steps and call submit_assessment once."


class LeadNotFoundError(NotFoundError):
    code = "lead_not_found"

    def __init__(self) -> None:
        # The same answer whether the lead does not exist, is another organisation's or is not
        # one the asker may read.
        super().__init__("Lead not found.")


class AssessmentInvalidError(DomainError):
    status_code = 422
    code = "assessment_invalid"


class RateLimitedError(DomainError):
    status_code = 429
    code = "qualifier_rate_limited"


@dataclass(frozen=True)
class Limits:
    """How often assessments may be asked for (settings ``CRM_QUALIFIER_PER_*``)."""

    per_lead_hour: int
    per_user_hour: int
    per_tenant_day: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "Limits":
        return cls(
            settings.qualifier_per_lead_hour,
            settings.qualifier_per_user_hour,
            settings.qualifier_per_tenant_day,
        )

    @classmethod
    def default(cls) -> "Limits":
        fields = Settings.model_fields
        return cls(
            int(fields["qualifier_per_lead_hour"].default),
            int(fields["qualifier_per_user_hour"].default),
            int(fields["qualifier_per_tenant_day"].default),
        )


@dataclass(frozen=True)
class AssessmentResult:
    assessment: LeadAssessment
    proposal: AgentAction | None
    # Why the approvals module refused the proposal (the Sentinel), if it did.
    blocked_message: str | None = None


def _clean_all(items: list[str]) -> list[str]:
    return [screen(item).clean for item in items]


def _refuse(reason: str, error: DomainError) -> DomainError:
    QUALIFIER_REFUSALS.labels(reason=reason).inc()
    return error


def _check_limits(
    session: Session,
    principal: Principal,
    tenant_id: uuid.UUID,
    lead_id: uuid.UUID,
    limits: Limits,
    now: datetime,
) -> None:
    hour, day = now - timedelta(hours=1), now - timedelta(days=1)
    if (
        repository.count_assessments(session, tenant_id, since=hour, lead_id=lead_id)
        >= limits.per_lead_hour
    ):
        raise _refuse(
            "lead_limit",
            RateLimitedError("This lead was assessed a moment ago. Try again in an hour."),
        )
    if (
        repository.count_assessments(session, tenant_id, since=hour, user_id=principal.user_id)
        >= limits.per_user_hour
    ):
        raise _refuse(
            "user_limit", RateLimitedError("You have asked for many assessments. Try again later.")
        )
    if repository.count_assessments(session, tenant_id, since=day) >= limits.per_tenant_day:
        raise _refuse(
            "tenant_limit",
            RateLimitedError("Your organisation reached its daily limit for assessments."),
        )


def assess_lead(
    session: Session,
    principal: Principal,
    model: ChatModel,
    lead_id: uuid.UUID,
    *,
    limits: Limits | None = None,
    ai_limits: agents_api.Limits | None = None,
    now: datetime | None = None,
) -> AssessmentResult:
    if (
        principal.tenant_id is None
        or principal.user_id is None
        or principal.user_type != "staff"
        or not principal.has_permission(Permission.QUALIFIER_RUN)
    ):
        raise ForbiddenError("You may not do this.")
    tenant_id = principal.tenant_id
    when = now or datetime.now(UTC)
    procedure = repository.get_active(session, tenant_id)
    if procedure is None:
        raise _refuse("no_procedure", NoActiveProcedureError())
    facts = leads_api.qualifier_facts(session, principal, lead_id)
    if facts is None:
        raise _refuse("lead_not_found", LeadNotFoundError())
    _check_limits(session, principal, tenant_id, lead_id, limits or Limits.default(), when)

    # The registry gate (ADR 0016): off, over budget or the tool taken away stops it here.
    governed = agents_api.governed(model, session, tenant_id, AGENT, ai_limits or _default_ai())
    if not governed.available:
        governed.reply(system="", messages=[], tools=[])  # raises "not configured"

    steps = list(procedure.steps)
    shown, field_names, suspicious = rules.model_view(facts)
    reply = governed.reply(
        system=rules.system_prompt(steps, shown, suspicious),
        messages=[{"role": "user", "content": ASK}],
        tools=[rules.submit_tool(len(steps))],
    )
    uses = reply.tool_uses
    if len(uses) != 1 or uses[0].name != rules.TOOL_NAME:
        raise _refuse(
            "invalid_answer",
            AssessmentInvalidError("The assistant did not return exactly one assessment."),
        )
    try:
        parsed = rules.parse_assessment(uses[0].input, len(steps))
    except rules.AssessmentRefused as refusal:
        raise _refuse("invalid_answer", AssessmentInvalidError(str(refusal))) from None

    planned = rules.plan(parsed, facts, procedure.version)
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
                    target_id=lead_id,
                    payload=planned.payload,
                    reason=planned.reason,
                    agent=AGENT,
                )
        except approvals_api.ProposalBlockedError as refusal:
            # Outside the savepoint, so the audit entry of the refusal stays with the request.
            approvals_api.audit_blocked(session, principal, refusal)
            blocked = refusal.detail

    outcome = "proposed" if proposal else ("blocked" if blocked else "no_proposal")
    record = LeadAssessment(
        tenant_id=tenant_id,
        lead_id=lead_id,
        procedure_id=procedure.id,
        procedure_version=procedure.version,
        requested_by_user_id=principal.user_id,
        decision=parsed.decision,
        matched_steps=sorted(parsed.matched_steps),
        reasons=_clean_all(parsed.reasons),
        missing=_clean_all(parsed.missing),
        fields_given=field_names,
        outcome=outcome,
        proposal_id=proposal.id if proposal else None,
    )
    session.add(record)
    session.flush()
    # Ids and codes only - not the reasons, which are text a model wrote.
    record_audit(
        session,
        principal,
        action="qualifier.assessed",
        entity_type="lead",
        entity_id=lead_id,
        changes={
            "assessment_id": str(record.id),
            "decision": parsed.decision,
            "outcome": outcome,
            "procedure_version": procedure.version,
            "proposal_id": str(proposal.id) if proposal else None,
        },
    )
    QUALIFIER_ASSESSMENTS.labels(decision=parsed.decision, outcome=outcome).inc()
    return AssessmentResult(record, proposal, blocked)


def _default_ai() -> agents_api.Limits:
    return agents_api.Limits.default()
