"""Asking the deal desk to review one deal (ADR 0024, step DD2).

    permission ─► limits ─► graph:
        read (a deal the asker may read; a sales agent only their own) ─► registry
        ─► three reviewers in parallel (model only, no database work in their threads)
        ─► desk lead (governed model) ─► at most two proposals (approvals + Sentinel)
    ─► reviewers' tokens counted ─► review stored (insert-only) ─► audit

It only ever PROPOSES follow-up tasks on the deal: a different person approves them. Services never
commit; the router does.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog, record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.config import Settings
from app.core.errors import DomainError, ForbiddenError, NotFoundError
from app.core.observability.metrics import ai_agent
from app.modules.agents import api as agents_api
from app.modules.approvals import api as approvals_api
from app.modules.approvals.models import AgentAction
from app.modules.assistant.api import ChatModel, ModelReply
from app.modules.deal_desk import graph, repository, review
from app.modules.deal_desk.facts import DealNotFoundError, build_sheets
from app.modules.deal_desk.models import DealReview
from app.modules.deal_desk.rules import DealSheets, FactSheet, Reviewer
from app.modules.sales import api as sales_api

AGENT = "deal_desk"
AUDIT_ACTION = "deal_desk.reviewed"
ASK = "Review this and call the tool exactly once."
RETENTION = timedelta(days=365)  # the database enforces the same figure (migration 0052)
LIST_LIMIT = 20


class OnlyTheOwnerError(ForbiddenError):
    code = "deal_desk_owner_only"

    def __init__(self) -> None:
        super().__init__("Only the deal's owner or a manager can ask the deal desk.")


class RateLimitedError(DomainError):
    status_code = 429
    code = "deal_desk_rate_limited"


class NoReviewerAnsweredError(DomainError):
    status_code = 422
    code = "deal_desk_no_answer"

    def __init__(self) -> None:
        super().__init__("None of the reviewers gave a usable answer. Nothing was stored.")


class BriefInvalidError(DomainError):
    status_code = 422
    code = "deal_desk_invalid_answer"


@dataclass(frozen=True)
class Limits:
    """How often the deal desk may run (settings ``CRM_DEAL_DESK_PER_*``)."""

    per_deal_hour: int
    per_tenant_day: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "Limits":
        return cls(settings.deal_desk_per_deal_hour, settings.deal_desk_per_tenant_day)

    @classmethod
    def default(cls) -> "Limits":
        fields = Settings.model_fields
        return cls(
            int(fields["deal_desk_per_deal_hour"].default),
            int(fields["deal_desk_per_tenant_day"].default),
        )


@dataclass(frozen=True)
class ReviewResult:
    review: DealReview
    proposals: list[AgentAction]
    blocked: list[str]


def _asker(principal: Principal) -> tuple[uuid.UUID, uuid.UUID]:
    if (
        principal.tenant_id is None
        or principal.user_id is None
        or principal.user_type != "staff"
        or not principal.has_permission(Permission.DEAL_DESK_RUN)
    ):
        raise ForbiddenError("You may not do this.")
    return principal.tenant_id, principal.user_id


def count_runs(
    session: Session, tenant_id: uuid.UUID, since: datetime, deal_id: uuid.UUID | None = None
) -> int:
    query = select(func.count()).where(
        AuditLog.tenant_id == tenant_id,
        AuditLog.action == AUDIT_ACTION,
        AuditLog.occurred_at >= since,
    )
    if deal_id is not None:
        query = query.where(AuditLog.entity_id == deal_id)
    return int(session.scalar(query) or 0)


def _check_limits(
    session: Session, tenant_id: uuid.UUID, deal_id: uuid.UUID, limits: Limits, now: datetime
) -> None:
    if count_runs(session, tenant_id, now - timedelta(hours=1), deal_id) >= limits.per_deal_hour:
        raise RateLimitedError("This deal was reviewed a moment ago. Try again in an hour.")
    if count_runs(session, tenant_id, now - timedelta(days=1)) >= limits.per_tenant_day:
        raise RateLimitedError("Your organisation reached its daily limit for the deal desk.")


def _tokens(reply: Any) -> tuple[int, int]:
    usage = getattr(reply, "usage", None) or {}
    return int(usage.get("input_tokens", 0) or 0), int(usage.get("output_tokens", 0) or 0)


def run_review(
    session: Session,
    principal: Principal,
    model: ChatModel,
    opportunity_id: uuid.UUID,
    *,
    limits: Limits | None = None,
    ai_limits: agents_api.Limits | None = None,
    now: datetime | None = None,
) -> ReviewResult:
    tenant_id, user_id = _asker(principal)
    when = now or datetime.now(UTC)
    gate = ai_limits or agents_api.Limits.default()
    _check_limits(session, tenant_id, opportunity_id, limits or Limits.default(), when)
    if not model.available:
        model.reply(system="", messages=[], tools=[])  # raises "not configured"
    governed = agents_api.governed(model, session, tenant_id, AGENT, gate)
    allowed: set[str] = set()
    replies: list[ModelReply] = []  # reviewers' raw replies, counted after the join
    lead_reply: list[ModelReply] = []
    blocked: list[str] = []

    def read() -> DealSheets | None:
        deal = sales_api.deal_facts(session, principal, opportunity_id)
        if deal is None:
            return None
        if not principal.has_permission(Permission.OPPORTUNITY_READ_ALL) and (
            deal.owner_id != user_id
        ):
            raise OnlyTheOwnerError()
        # The registry (ADR 0016) after the deal, so an unreadable deal is "not found" either
        # way; a switched-off or exhausted agent is refused here, before any model call.
        state = agents_api.check_can_call(session, tenant_id, AGENT, gate, when)
        allowed.update(state.allowed_tools)
        return build_sheets(session, principal, opportunity_id, when)

    def review_one(name: Reviewer, sheet: FactSheet) -> graph.ReviewerAnswer:
        # Runs in a thread of its own: the model call only, no database work.
        tools = [review.findings_tool()] if review.FINDINGS_TOOL in allowed else []
        with ai_agent(AGENT):
            reply = model.reply(
                system=review.reviewer_prompt(sheet),
                messages=[{"role": "user", "content": ASK}],
                tools=tools,
            )
        replies.append(reply)
        uses = [use for use in reply.tool_uses if use.name in allowed]
        try:
            findings = review.parse_findings(uses, sheet)
        except review.AnswerRefusedError:
            return graph.ReviewerAnswer(name, None, reply=reply)
        return graph.ReviewerAnswer(name, findings, reply=reply)

    def lead(findings: list[review.Finding], silent: list[Reviewer]) -> review.Brief:
        reply = governed.reply(
            system=review.lead_prompt(findings, silent),
            messages=[{"role": "user", "content": ASK}],
            tools=[review.brief_tool()],
        )
        lead_reply.append(reply)
        try:
            return review.parse_brief(reply.tool_uses)
        except review.AnswerRefusedError as refusal:
            raise BriefInvalidError(str(refusal)) from None

    def propose(task: review.TaskPlan) -> AgentAction | None:
        try:
            with session.begin_nested():  # a refused proposal leaves nothing behind
                return approvals_api.propose(
                    session,
                    principal,
                    kind="activity.create_task",
                    target_type="opportunity",
                    target_id=opportunity_id,
                    payload={"subject": task.subject, "due_in_days": task.due_in_days},
                    reason=task.reason,
                    agent=AGENT,
                )
        except approvals_api.ProposalBlockedError as refusal:
            approvals_api.audit_blocked(session, principal, refusal)
            blocked.append(refusal.detail)
            return None

    try:
        result = graph.run(graph.Ports(read, review_one, lead, propose))
    finally:
        # The reviewers' tokens, counted here in one thread (the desk lead's were counted by the
        # governed model). Also when something failed: a model call that ran has cost tokens.
        for reply in replies:
            used_in, used_out = _tokens(reply)
            agents_api.record_usage(
                session,
                tenant_id,
                AGENT,
                input_tokens=used_in,
                output_tokens=used_out,
                limits=gate,
                now=when,
            )
    if result.outcome == "deal_not_found":
        raise DealNotFoundError()
    if result.outcome == "no_reviewer_answered" or result.brief is None:
        raise NoReviewerAnsweredError()

    proposals: list[AgentAction] = [p for p in result.proposals if p is not None]
    totals = [_tokens(r) for r in [*replies, *lead_reply]]
    stored = repository.add_review(
        session,
        DealReview(
            tenant_id=tenant_id,
            opportunity_id=opportunity_id,
            requested_by_user_id=user_id,
            brief=result.brief.text,
            findings=[f.as_json() for a in result.answers for f in (a.findings or [])],
            reviewers={
                a.reviewer: "answered" if a.findings is not None else "refused"
                for a in result.answers
            },
            proposal_ids=[str(p.id) for p in proposals],
            input_tokens=sum(i for i, _ in totals),
            output_tokens=sum(o for _, o in totals),
        ),
    )
    # Ids, codes and counts only - never what a model wrote.
    record_audit(
        session,
        principal,
        action=AUDIT_ACTION,
        entity_type="opportunity",
        entity_id=opportunity_id,
        changes={
            "review_id": str(stored.id),
            "reviewers": stored.reviewers,
            "findings": len(stored.findings),
            "proposal_ids": stored.proposal_ids,
            "blocked": len(blocked),
        },
    )
    # The limits count these audit rows: write it now, so a second run in the same session sees it.
    session.flush()
    return ReviewResult(stored, proposals, blocked)


def list_reviews(
    session: Session, principal: Principal, opportunity_id: uuid.UUID
) -> list[DealReview]:
    """The reviews of a deal, newest first, for someone who may read the deal."""
    if principal.tenant_id is None or principal.user_type != "staff":
        raise NotFoundError("Deal not found.")
    if not sales_api.is_readable_opportunity(session, principal, opportunity_id):
        raise DealNotFoundError()
    return list(repository.list_for_deal(session, principal.tenant_id, opportunity_id, LIST_LIMIT))


def delete_expired(session: Session, now: datetime, *, tenant_id: uuid.UUID) -> int:
    """Delete reviews older than the retention (the worker, per organisation)."""
    return repository.delete_older_than(session, tenant_id, now - RETENTION)
