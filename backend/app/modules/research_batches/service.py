"""Batch account research, asking and starting (ADR 0042, step BR2).

``estimate`` is a read: it works out who would be researched and what it would cost, calls no model
and writes nothing. ``start`` does it again from scratch (never trusting what the screen showed),
refuses if the figure the person confirmed no longer holds, and then writes the batch and its
frozen list of accounts in the caller's transaction. Services never commit.

Nothing here researches an account: the worker step of BR3 does, one account at a time, as the
person who started the batch. Until BR3 a started batch only waits.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.config import Settings
from app.core.errors import ConflictError, DomainError, ForbiddenError, NotFoundError
from app.modules.accounts import api as accounts_api
from app.modules.agents import api as agents_api
from app.modules.deal_desk import api as deal_desk_api
from app.modules.research_batches import repository, rules
from app.modules.research_batches.models import ResearchBatch, ResearchBatchItem
from app.modules.saved_filters import api as saved_filters_api

ENTITY = "research_batch"
BATCHES = "research_batches"  # the registry entry that switches the feature
RESEARCH = "account_research"  # the registry entry whose model calls a batch makes
DEFAULT_TYPICAL_TOKENS = 3000  # shown when the organisation has no briefs yet; screen only


class BatchNotFoundError(NotFoundError):
    code = "research_batch_not_found"

    def __init__(self) -> None:
        super().__init__("There is no such research batch.")


class SelectionError(DomainError):
    """The chosen accounts cannot make a batch (none usable, too many); the code is the rule's."""

    status_code = 422

    def __init__(self, error: rules.BatchRuleError) -> None:
        super().__init__(str(error))
        self.code = error.code


class BatchLimitError(DomainError):
    status_code = 429
    code = "research_batch_limit"


class DailyLimitError(DomainError):
    status_code = 429
    code = "research_daily_limit"


class EstimateChangedError(ConflictError):
    code = "estimate_changed"

    def __init__(self) -> None:
        super().__init__("The cost changed since you looked at it. Look at the new estimate first.")


class BudgetTooSmallError(ConflictError):
    code = "research_budget_too_small"

    def __init__(self) -> None:
        super().__init__(
            "This month's AI budget for account research is too small for even one account. "
            "Ask an administrator to raise it, or choose fewer accounts."
        )


@dataclass(frozen=True)
class BatchRequest:
    """What a person asks for. Only these fields come from the client."""

    source: str  # "filter" or "rows"
    saved_filter_id: uuid.UUID | None = None
    account_ids: tuple[uuid.UUID, ...] = ()
    research_again: bool = False


@dataclass(frozen=True)
class Estimate:
    selection: rules.Selection
    reused: tuple[tuple[uuid.UUID, uuid.UUID], ...]  # (account, the brief that is reused)
    accounts_calling_model: int
    upper_bound_tokens: int
    typical_tokens: int
    estimated_cost_usd: Decimal | None  # None: no price set, never "free"
    cap_tokens: int  # what the batch could use: the upper bound, held to the monthly budget
    monthly_tokens_left: int | None
    daily_left: int
    worst_case: rules.WorstCase


def _ids(principal: Principal) -> tuple[uuid.UUID, uuid.UUID]:
    if principal.tenant_id is None or principal.user_id is None or principal.user_type != "staff":
        raise ForbiddenError("Batch research is for staff of an organisation.")
    return principal.tenant_id, principal.user_id


def _check_permission(principal: Principal) -> None:
    if not principal.has_permission(Permission.RESEARCH_BATCH_RUN) or not principal.has_permission(
        Permission.ACCOUNT_RESEARCH_RUN
    ):
        raise ForbiddenError("You may not research accounts in batches.")


def worst_case(settings: Settings) -> rules.WorstCase:
    return rules.WorstCase(
        settings.research_batch_worst_input_tokens, settings.assistant_max_tokens
    )


def _resolve(
    session: Session, principal: Principal, request: BatchRequest, cap: int
) -> rules.Selection:
    try:
        if request.source == "rows":
            found = accounts_api.batch_candidates(session, principal, list(request.account_ids))
            return rules.resolve_rows(
                list(request.account_ids),
                [rules.Candidate(account_id, archived) for account_id, archived in found],
                cap=cap,
            )
        if request.source == "filter":
            if request.saved_filter_id is None:
                raise rules.BatchRuleError("empty_selection", "Choose a saved filter.")
            params = saved_filters_api.filter_params(session, principal, request.saved_filter_id)
            ids, total = accounts_api.find_for_batch(session, principal, params, limit=cap)
            return rules.resolve_filter(
                [rules.Candidate(account_id) for account_id in ids], total_matching=total, cap=cap
            )
    except rules.BatchRuleError as error:
        raise SelectionError(error) from None
    raise SelectionError(rules.BatchRuleError("bad_source", "Choose a saved filter or accounts."))


def estimate(
    session: Session,
    principal: Principal,
    request: BatchRequest,
    settings: Settings,
    now: datetime | None = None,
) -> Estimate:
    """Who would be researched and what it could cost. Writes nothing, calls no model."""
    tenant_id, user_id = _ids(principal)
    _check_permission(principal)
    when = now or datetime.now(UTC)
    limits = agents_api.Limits.from_settings(settings)
    # Both switches: the batch feature's own, and the account research whose calls it makes.
    agents_api.check_can_call(session, tenant_id, BATCHES, limits, when)
    research = agents_api.check_can_call(session, tenant_id, RESEARCH, limits, when)

    if repository.running_for_person(session, tenant_id, user_id) >= (
        settings.research_batch_running_per_person
    ):
        raise BatchLimitError("You already have a batch running. Wait for it or stop it first.")
    if (
        repository.running_for_tenant(session, tenant_id)
        >= settings.research_batch_running_per_tenant
    ):
        raise BatchLimitError("Your organisation already has the most batches it may run at once.")
    if repository.started_by_person_since(
        session, tenant_id, user_id, when - timedelta(days=1)
    ) >= (settings.research_batch_per_person_day):
        raise BatchLimitError("You reached today's limit for starting batches.")

    selection = _resolve(session, principal, request, settings.research_batch_max)

    latest = deal_desk_api.latest_overviews(session, principal, list(selection.accounts))
    reused = tuple(
        (account, latest[account].brief_id)
        for account in selection.accounts
        if account in latest
        and rules.is_reusable(latest[account].created_at, when, again=request.research_again)
    )
    calling = len(selection.accounts) - len(reused)

    daily_left = max(
        0,
        settings.account_research_per_tenant_day
        - deal_desk_api.researched_today(session, tenant_id, when),
    )
    if calling > daily_left:
        raise DailyLimitError(
            f"Your organisation may write {daily_left} more account briefs today; "
            f"this batch needs {calling}. Choose fewer accounts."
        )

    worst = worst_case(settings)
    typical = deal_desk_api.recent_average_tokens(session, tenant_id) or DEFAULT_TYPICAL_TOKENS
    tokens = rules.estimate_tokens(calling, worst, typical)
    monthly_left = max(0, research.budget - research.used_tokens)
    cap = rules.token_cap(tokens.upper_bound_tokens, monthly_left)
    cost = agents_api.estimate_cost_usd(
        calling * worst.input_tokens,
        calling * worst.output_tokens,
        uses_model=True,
        input_price_per_million=settings.ai_input_price_per_million,
        output_price_per_million=settings.ai_output_price_per_million,
    )
    return Estimate(
        selection=selection,
        reused=reused,
        accounts_calling_model=calling,
        upper_bound_tokens=tokens.upper_bound_tokens,
        typical_tokens=tokens.typical_tokens,
        estimated_cost_usd=cost,
        cap_tokens=cap,
        monthly_tokens_left=monthly_left,
        daily_left=daily_left,
        worst_case=worst,
    )


def start(
    session: Session,
    principal: Principal,
    request: BatchRequest,
    settings: Settings,
    *,
    confirmed_upper_bound: int,
    now: datetime | None = None,
) -> ResearchBatch:
    """Write the batch and its frozen list of accounts. The estimate is worked out again here; the
    figure the person confirmed must still hold (within 20 %)."""
    tenant_id, user_id = _ids(principal)
    when = now or datetime.now(UTC)
    current = estimate(session, principal, request, settings, when)
    if not rules.estimate_still_matches(confirmed_upper_bound, current.upper_bound_tokens):
        raise EstimateChangedError
    if current.accounts_calling_model > 0 and not rules.may_start_next(
        0, current.worst_case, current.cap_tokens
    ):
        raise BudgetTooSmallError

    reused = dict(current.reused)
    all_reused = current.accounts_calling_model == 0
    batch = ResearchBatch(
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        status="finished" if all_reused else "running",
        finished_at=when if all_reused else None,
        source=request.source,
        saved_filter_id=request.saved_filter_id if request.source == "filter" else None,
        account_count=len(current.selection.accounts),
        not_available_count=current.selection.not_available,
        archived_count=current.selection.archived,
        estimated_upper_tokens=current.upper_bound_tokens,
        estimated_cost_usd=current.estimated_cost_usd,
        token_cap=current.cap_tokens,
        research_again=request.research_again,
    )
    session.add(batch)
    session.flush()
    for position, account in enumerate(current.selection.accounts, start=1):
        brief = reused.get(account)
        session.add(
            ResearchBatchItem(
                tenant_id=tenant_id,
                batch_id=batch.id,
                position=position,
                account_id=account,
                status="reused" if brief else "queued",
                brief_id=brief,
                finished_at=when if brief else None,
            )
        )
    session.flush()
    # One batch is counted on the AI agents page (no tokens: the model calls are counted under
    # account research when they happen).
    agents_api.record_usage(
        session,
        tenant_id,
        BATCHES,
        input_tokens=0,
        output_tokens=0,
        limits=agents_api.Limits.from_settings(settings),
        now=when,
    )
    record_audit(
        session,
        principal,
        action="research_batch.started",
        entity_type=ENTITY,
        entity_id=batch.id,
        changes={
            "source": request.source,
            "accounts": batch.account_count,
            "reused": len(current.reused),
            "calling_model": current.accounts_calling_model,
            "not_available": batch.not_available_count,
            "archived": batch.archived_count,
            "token_cap": batch.token_cap,
        },
    )
    return batch


def get_batch(
    session: Session, principal: Principal, batch_id: uuid.UUID
) -> tuple[ResearchBatch, list[ResearchBatchItem]]:
    """A batch of the person's organisation, with its items; for people who may run batches."""
    tenant_id, _ = _ids(principal)
    _check_permission(principal)
    batch = repository.get(session, tenant_id, batch_id)
    if batch is None:
        raise BatchNotFoundError
    return batch, repository.items(session, tenant_id, batch_id)


def list_batches(
    session: Session, principal: Principal, *, limit: int = 20, offset: int = 0
) -> tuple[list[ResearchBatch], int]:
    tenant_id, _ = _ids(principal)
    _check_permission(principal)
    return repository.list_batches(session, tenant_id, limit=limit, offset=offset)
