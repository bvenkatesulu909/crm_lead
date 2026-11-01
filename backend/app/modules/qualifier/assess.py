"""Asking the Qualifier to assess one lead (docs/qualifier.md, QA2).

    permission ─► active procedure ─► the lead (only if the asker may read it) ─► model
        ─► strict check of its ONE tool call ─► at most one proposal ─► one insert-only record

The model sees one lead and the written steps; it can call one tool that only reports what it
thinks. This file turns that into a proposal for the approval queue (never a change), through
the approvals module and its Sentinel. The model is passed in: QA3 wraps it in the agent
registry (switch, budget); here a scripted model is enough. Services never commit.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.errors import DomainError, ForbiddenError, NotFoundError
from app.core.screening import screen
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


@dataclass(frozen=True)
class AssessmentResult:
    assessment: LeadAssessment
    proposal: AgentAction | None
    # Why the approvals module refused the proposal (the Sentinel), if it did.
    blocked_message: str | None = None


def _clean_all(items: list[str]) -> list[str]:
    return [screen(item).clean for item in items]


def assess_lead(
    session: Session,
    principal: Principal,
    model: ChatModel,
    lead_id: uuid.UUID,
) -> AssessmentResult:
    if (
        principal.tenant_id is None
        or principal.user_id is None
        or principal.user_type != "staff"
        or not principal.has_permission(Permission.QUALIFIER_RUN)
    ):
        raise ForbiddenError("You may not do this.")
    procedure = repository.get_active(session, principal.tenant_id)
    if procedure is None:
        raise NoActiveProcedureError
    facts = leads_api.qualifier_facts(session, principal, lead_id)
    if facts is None:
        raise LeadNotFoundError

    steps = list(procedure.steps)
    shown, field_names, suspicious = rules.model_view(facts)
    reply = model.reply(
        system=rules.system_prompt(steps, shown, suspicious),
        messages=[{"role": "user", "content": ASK}],
        tools=[rules.submit_tool(len(steps))],
    )
    uses = reply.tool_uses
    if len(uses) != 1 or uses[0].name != rules.TOOL_NAME:
        raise AssessmentInvalidError("The assistant did not return exactly one assessment.")
    try:
        parsed = rules.parse_assessment(uses[0].input, len(steps))
    except rules.AssessmentRefused as refusal:
        raise AssessmentInvalidError(str(refusal)) from None

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
        tenant_id=principal.tenant_id,
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
    return AssessmentResult(record, proposal, blocked)
