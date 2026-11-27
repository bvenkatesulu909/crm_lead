"""Pure rules of batch account research (ADR 0042, step BR1): no database, no model.

A batch is a frozen list of at most 100 accounts, researched one at a time. These rules decide
what goes into the list, what a batch may cost, when it must stop and how its state moves. Money is
never computed here: only token counts (the service turns tokens into an estimate with the agents
module's price pair).
"""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

MAX_BATCH = 100  # a setting may lower it, never raise it (ADR 0042 BR2)
REUSE_WINDOW = timedelta(hours=24)
ESTIMATE_TOLERANCE_PERCENT = 20

BATCH_STATUSES = ("running", "finished", "cancelled", "stopped_budget", "stopped_error")
ITEM_STATUSES = ("queued", "running", "done", "reused", "skipped", "failed", "not_run")
FINISHED_ITEMS = ("done", "reused", "skipped", "failed", "not_run")
FAILURE_CODES = (
    "no_sourced_sentence",
    "answer_refused",
    "unavailable",
    "over_budget",
    "not_readable",
    "rate_limited",
    "error",
)
SOURCES = ("filter", "rows")

# queued -> running -> one end state; an item that never started may be skipped or not run.
_ITEM_MOVES: dict[str, tuple[str, ...]] = {
    "queued": ("running", "reused", "skipped", "not_run"),
    "running": (
        "done",
        "failed",
        "skipped",
        "queued",
    ),  # queued again = a retry of a temporary error
    "done": (),
    "reused": (),
    "skipped": (),
    "failed": (),
    "not_run": (),
}


class BatchRuleError(ValueError):
    """A request the rules refuse; ``code`` is stable, the message is safe to show."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# --- who goes into the batch ---------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    """An account the PERSON may read, as the scoped repository returned it."""

    account_id: uuid.UUID
    archived: bool = False


@dataclass(frozen=True)
class Selection:
    accounts: tuple[uuid.UUID, ...]  # frozen, in order, no duplicates
    not_available: int  # asked for, but not readable / not found / another organisation's
    archived: int  # readable but archived: skipped with a visible reason


def resolve_rows(
    asked: Sequence[uuid.UUID], readable: Iterable[Candidate], *, cap: int = MAX_BATCH
) -> Selection:
    """Ticked rows. Ids the person may not read, that do not exist or belong to another
    organisation are all the same thing here: they are not in ``readable``, so they are counted and
    never named. Duplicates are ignored. More than ``cap`` distinct ids is refused, not cut."""
    if cap < 1 or cap > MAX_BATCH:
        raise ValueError("the cap is between 1 and the maximum batch size")
    distinct = list(dict.fromkeys(asked))
    if not distinct:
        raise BatchRuleError("empty_selection", "Choose at least one account.")
    if len(distinct) > cap:
        raise BatchRuleError(
            "batch_too_large", f"A batch holds at most {cap} accounts; you chose {len(distinct)}."
        )
    known = {c.account_id: c for c in readable}
    chosen: list[uuid.UUID] = []
    archived = 0
    for account_id in distinct:
        found = known.get(account_id)
        if found is None:
            continue
        if found.archived:
            archived += 1
            continue
        chosen.append(account_id)
    not_available = len(distinct) - len(chosen) - archived
    return _checked(chosen, not_available, archived)


def resolve_filter(
    matches: Sequence[Candidate], *, total_matching: int, cap: int = MAX_BATCH
) -> Selection:
    """A saved filter. ``matches`` is the list the person's own account search returned (it has
    already applied their read rules), ``total_matching`` how many accounts matched in all. More
    than ``cap`` matches is refused with the number, so the person narrows the filter."""
    if cap < 1 or cap > MAX_BATCH:
        raise ValueError("the cap is between 1 and the maximum batch size")
    if total_matching > cap:
        raise BatchRuleError(
            "batch_too_large",
            f"The filter finds {total_matching} accounts; a batch holds at most {cap}. "
            "Narrow the filter.",
        )
    seen: dict[uuid.UUID, Candidate] = {}
    for candidate in matches:
        seen.setdefault(candidate.account_id, candidate)
    chosen = [c.account_id for c in seen.values() if not c.archived]
    archived = sum(1 for c in seen.values() if c.archived)
    return _checked(chosen, 0, archived)


def _checked(chosen: list[uuid.UUID], not_available: int, archived: int) -> Selection:
    if not chosen:
        raise BatchRuleError("empty_selection", "None of the chosen accounts can be researched.")
    return Selection(tuple(chosen), not_available, archived)


def is_reusable(brief_created_at: datetime | None, now: datetime, *, again: bool = False) -> bool:
    """A brief younger than 24 hours is reused instead of researching the account again, unless
    the person ticked "research again anyway"."""
    if again or brief_created_at is None:
        return False
    return now - brief_created_at < REUSE_WINDOW


# --- what a batch may cost -----------------------------------------------------------------------


@dataclass(frozen=True)
class WorstCase:
    """The most one account's research can use: the writer's fixed input cap plus its output cap."""

    input_tokens: int
    output_tokens: int

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class TokenEstimate:
    accounts_calling_model: int
    upper_bound_tokens: int  # accounts x worst case: what the cap is built from
    typical_tokens: int  # accounts x the organisation's recent average, for the screen only


def estimate_tokens(
    accounts_calling_model: int, worst: WorstCase, typical_per_account: int
) -> TokenEstimate:
    if accounts_calling_model < 0 or typical_per_account < 0:
        raise ValueError("counts cannot be negative")
    typical = min(typical_per_account, worst.total)
    return TokenEstimate(
        accounts_calling_model,
        accounts_calling_model * worst.total,
        accounts_calling_model * typical,
    )


def estimate_still_matches(shown_upper_bound: int, current_upper_bound: int) -> bool:
    """The figure the person confirmed must still be true when they press Start: within 20 %."""
    if shown_upper_bound < 0 or current_upper_bound < 0:
        raise ValueError("token counts cannot be negative")
    if shown_upper_bound == current_upper_bound:
        return True
    if shown_upper_bound == 0:
        return False
    drift = abs(current_upper_bound - shown_upper_bound) * 100
    return drift <= shown_upper_bound * ESTIMATE_TOLERANCE_PERCENT


def token_cap(confirmed_upper_bound: int, monthly_tokens_left: int | None) -> int:
    """The batch's hard cap: what the person confirmed, and never more than the agent's monthly
    budget has left (``None`` = the agent has no budget). Never negative."""
    if confirmed_upper_bound < 0:
        raise ValueError("token counts cannot be negative")
    if monthly_tokens_left is None:
        return confirmed_upper_bound
    return max(0, min(confirmed_upper_bound, monthly_tokens_left))


def may_start_next(tokens_used: int, worst: WorstCase, cap: int) -> bool:
    """The hard stop. An item starts only if even its worst case still fits under the cap, so the
    cap cannot be passed - not even by the item running when it would be reached."""
    if tokens_used < 0 or cap < 0:
        raise ValueError("token counts cannot be negative")
    return tokens_used + worst.total <= cap


# --- how a batch moves ---------------------------------------------------------------------------


def can_move(item_from: str, item_to: str) -> bool:
    if item_from not in _ITEM_MOVES or item_to not in ITEM_STATUSES:
        raise ValueError("unknown item status")
    return item_to in _ITEM_MOVES[item_from]


def check_failure(status: str, failure_code: str | None) -> None:
    """A failed item names why; nothing else carries a failure code."""
    if status == "failed":
        if failure_code not in FAILURE_CODES:
            raise BatchRuleError("bad_failure_code", "A failed account needs a known reason.")
    elif failure_code is not None:
        raise BatchRuleError("bad_failure_code", "Only a failed account has a failure reason.")


def batch_outcome(
    item_statuses: Iterable[str],
    *,
    cancel_requested: bool,
    budget_stopped: bool,
    error_stopped: bool = False,
) -> str:
    """The state of the batch given its items: still running while any item can still move."""
    statuses = list(item_statuses)
    if any(s not in ITEM_STATUSES for s in statuses):
        raise ValueError("unknown item status")
    if any(s in ("queued", "running") for s in statuses):
        return "running"
    if error_stopped:
        return "stopped_error"
    if budget_stopped:
        return "stopped_budget"
    if cancel_requested:
        return "cancelled"
    return "finished"


def counts(item_statuses: Iterable[str]) -> dict[str, int]:
    """How many items are in each state (every state is present, zero included)."""
    result = dict.fromkeys(ITEM_STATUSES, 0)
    for status in item_statuses:
        if status not in result:
            raise ValueError("unknown item status")
        result[status] += 1
    return result


def conclude_unstarted(item_statuses: Sequence[str]) -> list[str]:
    """When a batch is cancelled or stopped, every queued item becomes ``not_run``; items that
    already ended, and the one running, stay as they are."""
    return ["not_run" if s == "queued" else s for s in item_statuses]
