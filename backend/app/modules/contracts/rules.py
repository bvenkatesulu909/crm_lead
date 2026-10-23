"""Contract rules: status flow and renewal dates. Pure functions, unit-tested."""

import calendar
from datetime import date, timedelta

from app.core.errors import ConflictError

TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"active"}),  # activate
    "active": frozenset({"terminated", "expired", "renewed"}),
    "expired": frozenset({"renewed"}),  # a renewal may still follow after the end date
    "terminated": frozenset(),
    "renewed": frozenset(),
}
# An active contract keeps its account, dates and value: changing those means renewing it.
EDITABLE_WHEN_ACTIVE = frozenset(
    {
        "title",
        "owner_id",
        "contact_id",
        "auto_renew",
        "renewal_notice_days",
        "renewal_term_months",
        "terms",
    }
)
# Fields that move the renewal date, so the reminder may have to go out again.
RENEWAL_DATE_FIELDS = frozenset({"end_date", "renewal_notice_days"})
RENEWABLE = frozenset({"active", "expired"})


class ContractStateError(ConflictError):
    code = "contract_state"


def check_transition(current: str, target: str) -> None:
    if target not in TRANSITIONS.get(current, frozenset()):
        raise ContractStateError(f"A contract cannot go from '{current}' to '{target}'.")


def label(number: int) -> str:
    return f"CT-{number:04d}"


def renewal_date(end_date: date, notice_days: int) -> date:
    """From this day the owner is reminded that the contract is about to end."""
    return end_date - timedelta(days=notice_days)


def add_months(start: date, months: int) -> date:
    """``start`` plus whole months; the day is cut back to the month's end (31 Jan + 1 = 28 Feb)."""
    index = start.month - 1 + months
    year, month = start.year + index // 12, index % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def renewal_end(new_start: date, term_months: int | None, old_length_days: int) -> date:
    """Last day of a renewal that starts on ``new_start``: the renewal term in months, or as
    long as the old contract when no term is set."""
    if term_months:
        return add_months(new_start, term_months) - timedelta(days=1)
    return new_start + timedelta(days=old_length_days)


def renewal_defaults(start: date, end: date, term_months: int | None) -> tuple[date, date]:
    """Dates of the renewal: it starts the day after the old end."""
    new_start = end + timedelta(days=1)
    return new_start, renewal_end(new_start, term_months, (end - start).days)
