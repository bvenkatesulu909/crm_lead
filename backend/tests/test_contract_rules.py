"""Contract rules (pure functions, no database): status flow and renewal dates."""

from datetime import date

import pytest

from app.modules.contracts import rules

ALL = ("draft", "active", "expired", "terminated", "renewed")
ALLOWED = {
    ("draft", "active"),
    ("active", "terminated"),
    ("active", "expired"),
    ("active", "renewed"),
    ("expired", "renewed"),
}


@pytest.mark.parametrize("current", ALL)
@pytest.mark.parametrize("target", ALL)
def test_only_the_documented_transitions_are_allowed(current: str, target: str) -> None:
    if (current, target) in ALLOWED:
        rules.check_transition(current, target)
    else:
        with pytest.raises(rules.ContractStateError):
            rules.check_transition(current, target)


def test_a_finished_contract_cannot_change_status_again() -> None:
    for final in ("terminated", "renewed"):
        for target in ALL:
            with pytest.raises(rules.ContractStateError):
                rules.check_transition(final, target)


def test_labels_are_padded_and_per_number() -> None:
    assert rules.label(1) == "CT-0001"
    assert rules.label(42) == "CT-0042"
    assert rules.label(12345) == "CT-12345"


def test_renewal_date_is_the_notice_period_before_the_end() -> None:
    assert rules.renewal_date(date(2027, 3, 31), 30) == date(2027, 3, 1)
    assert rules.renewal_date(date(2027, 1, 10), 0) == date(2027, 1, 10)
    assert rules.renewal_date(date(2027, 1, 10), 365) == date(2026, 1, 10)


@pytest.mark.parametrize(
    "start, months, expected",
    [
        (date(2026, 1, 31), 1, date(2026, 2, 28)),  # cut back to the month's end
        (date(2028, 1, 31), 1, date(2028, 2, 29)),  # leap year
        (date(2026, 10, 15), 3, date(2027, 1, 15)),  # crosses the year
        (date(2026, 12, 1), 12, date(2027, 12, 1)),
        (date(2026, 5, 31), 6, date(2026, 11, 30)),
        (date(2026, 1, 1), 0, date(2026, 1, 1)),
    ],
)
def test_add_months_never_overflows_the_month(start: date, months: int, expected: date) -> None:
    assert rules.add_months(start, months) == expected


def test_a_renewal_with_a_term_lasts_that_many_months_less_a_day() -> None:
    # 12 months starting 1 Jan 2027 end on 31 Dec 2027.
    assert rules.renewal_end(date(2027, 1, 1), 12, 100) == date(2027, 12, 31)
    assert rules.renewal_end(date(2027, 3, 15), 6, 0) == date(2027, 9, 14)


def test_a_renewal_without_a_term_is_as_long_as_the_old_contract() -> None:
    old_start, old_end = date(2026, 1, 1), date(2026, 12, 31)  # 364 days between the dates
    start, end = rules.renewal_defaults(old_start, old_end, None)
    assert start == date(2027, 1, 1)  # the day after the old end
    assert (end - start).days == (old_end - old_start).days


def test_renewal_defaults_use_the_term_when_there_is_one() -> None:
    start, end = rules.renewal_defaults(date(2026, 1, 1), date(2026, 12, 31), 24)
    assert (start, end) == (date(2027, 1, 1), date(2028, 12, 31))


def test_what_an_active_contract_may_still_change() -> None:
    assert {"owner_id", "title", "terms", "auto_renew"} <= rules.EDITABLE_WHEN_ACTIVE
    # Money, dates, account and currency are changed by renewing, never by editing.
    for locked in ("start_date", "end_date", "total_value", "currency", "billing_frequency"):
        assert locked not in rules.EDITABLE_WHEN_ACTIVE
