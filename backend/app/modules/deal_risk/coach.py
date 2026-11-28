"""The optional deal risk coach (ADR 0037, DR5).

    permission ─► limits ─► the forecast the CODE works out (deal must be open and readable)
    ─► governed model (registry: switch, budget, tool filter, platform switch)
    ─► strict check ─► at most two follow-up tasks as proposals (approvals + Sentinel) ─► audit

The coach never scores and never changes a deal: its advice is returned to the asker, and its
tasks wait in the approval queue for a different person. Services never commit.
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
from app.core.errors import DomainError, ForbiddenError
from app.modules.agents import api as agents_api
from app.modules.approvals import api as approvals_api
from app.modules.approvals.models import AgentAction
from app.modules.assistant.api import ChatModel
from app.modules.deal_risk import coach_rules
from app.modules.deal_risk.service import compute

AGENT = "deal_risk_coach"
AUDIT_ACTION = "deal_risk.coached"
ASK = "Look at this forecast and call submit_advice once."


class AdviceInvalidError(DomainError):
    status_code = 422
    code = "deal_risk_coach_invalid_answer"


class CoachRateLimitedError(DomainError):
    status_code = 429
    code = "deal_risk_coach_rate_limited"


@dataclass(frozen=True)
class CoachLimits:
    """How often the coach may run (settings ``CRM_DEAL_RISK_COACH_PER_*``)."""

    per_deal_hour: int
    per_tenant_day: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "CoachLimits":
        return cls(settings.deal_risk_coach_per_deal_hour, settings.deal_risk_coach_per_tenant_day)

    @classmethod
    def default(cls) -> "CoachLimits":
        fields = Settings.model_fields
        return cls(
            int(fields["deal_risk_coach_per_deal_hour"].default),
            int(fields["deal_risk_coach_per_tenant_day"].default),
        )


@dataclass(frozen=True)
class CoachResult:
    advice: tuple[coach_rules.AdviceLine, ...]
    proposals: tuple[AgentAction, ...]
    blocked: tuple[str, ...]
    cleaned: bool


def _count(
    session: Session, tenant_id: uuid.UUID, since: datetime, deal: uuid.UUID | None = None
) -> int:
    query = select(func.count()).where(
        AuditLog.tenant_id == tenant_id,
        AuditLog.action == AUDIT_ACTION,
        AuditLog.occurred_at >= since,
    )
    if deal is not None:
        query = query.where(AuditLog.entity_id == deal)
    return int(session.scalar(query) or 0)


def run_coach(
    session: Session,
    principal: Principal,
    model: ChatModel,
    opp_id: uuid.UUID,
    *,
    limits: CoachLimits | None = None,
    ai_limits: agents_api.Limits | None = None,
    now: datetime | None = None,
) -> CoachResult:
    if (
        principal.tenant_id is None
        or principal.user_id is None
        or principal.user_type != "staff"
        or not principal.has_permission(Permission.DEAL_RISK_READ)
    ):
        raise ForbiddenError("You may not do this.")
    tenant_id = principal.tenant_id
    when = now or datetime.now(UTC)
    limit = limits or CoachLimits.default()
    if _count(session, tenant_id, when - timedelta(hours=1), opp_id) >= limit.per_deal_hour:
        raise CoachRateLimitedError("This deal was coached a moment ago. Try again in an hour.")
    if _count(session, tenant_id, when - timedelta(days=1)) >= limit.per_tenant_day:
        raise CoachRateLimitedError("Your organisation reached its daily limit for the coach.")

    # The forecast first: a deal the asker may not read, a closed deal or a made-up id is "not
    # found" before any model is asked.
    risk = compute(session, principal, opp_id, when)

    governed: ChatModel = agents_api.governed(
        model, session, tenant_id, AGENT, ai_limits or agents_api.Limits.default()
    )
    if not governed.available:
        governed.reply(system="", messages=[], tools=[])  # raises "switched off / not configured"
    reply = governed.reply(
        system=coach_rules.system_prompt(risk),
        messages=[{"role": "user", "content": ASK}],
        tools=[coach_rules.submit_tool([f.code for f in risk.factors])],
    )
    try:
        advice = coach_rules.parse(reply.tool_uses, risk)
    except coach_rules.AdviceRefusedError as refusal:
        raise AdviceInvalidError(str(refusal)) from None

    proposals: list[AgentAction] = []
    blocked: list[str] = []
    for task in advice.tasks:
        try:
            # A savepoint: a refused proposal leaves nothing behind.
            with session.begin_nested():
                proposals.append(
                    approvals_api.propose(
                        session,
                        principal,
                        kind="activity.create_task",
                        target_type="opportunity",
                        target_id=opp_id,
                        payload={"subject": task.subject, "due_in_days": task.due_in_days},
                        reason=coach_rules.task_reason(task, risk),
                        agent=AGENT,
                    )
                )
        except approvals_api.ProposalBlockedError as refusal:
            # Outside the savepoint, so the audit entry of the refusal stays with the request.
            approvals_api.audit_blocked(session, principal, refusal)
            blocked.append(refusal.detail)

    # Ids and counts only - not the advice, which is text a model wrote.
    record_audit(
        session,
        principal,
        action=AUDIT_ACTION,
        entity_type="opportunity",
        entity_id=opp_id,
        changes={
            "level": risk.level,
            "advice": len(advice.lines),
            "proposals": [str(p.id) for p in proposals],
            "blocked": len(blocked),
        },
    )
    # The limits count these rows: write now so a second run in the same session sees it.
    session.flush()
    return CoachResult(advice.lines, tuple(proposals), tuple(blocked), advice.cleaned)
