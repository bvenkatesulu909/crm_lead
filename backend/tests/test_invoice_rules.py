"""Invoice payment state and amount checks (pure functions, no database)."""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.invoices.rules import (
    InvalidAmountError,
    check_credit_amount,
    check_due_date,
    check_payment_amount,
    check_received_on,
    payment_state,
)

D = Decimal
TODAY = date(2026, 10, 18)


def state(**kw: object) -> str:
    base: dict[str, object] = {
        "status": "issued",
        "total": D("100.00"),
        "amount_paid": D("0"),
        "amount_credited": D("0"),
        "balance_due": D("100.00"),
        "due_date": date(2026, 11, 1),
        "today": TODAY,
    }
    return payment_state(**{**base, **kw})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"status": "draft"}, "draft"),
        ({"status": "discarded"}, "discarded"),
        ({}, "open"),
        ({"amount_paid": D("40"), "balance_due": D("60")}, "partially_paid"),
        ({"amount_credited": D("40"), "balance_due": D("60")}, "partially_paid"),
        ({"due_date": date(2026, 10, 17)}, "overdue"),
        ({"due_date": TODAY}, "open"),  # due today is not overdue yet
        ({"amount_paid": D("100"), "balance_due": D("0")}, "paid"),
        ({"amount_paid": D("100"), "balance_due": D("0"), "due_date": date(2020, 1, 1)}, "paid"),
        ({"amount_credited": D("100"), "balance_due": D("0")}, "credited"),
        ({"amount_paid": D("1"), "amount_credited": D("99"), "balance_due": D("0")}, "paid"),
    ],
)
def test_payment_state(changes: dict[str, object], expected: str) -> None:
    assert state(**changes) == expected


def test_payment_may_settle_but_not_exceed_the_balance() -> None:
    check_payment_amount(D("60.00"), D("60.00"))
    with pytest.raises(InvalidAmountError):
        check_payment_amount(D("60.01"), D("60.00"))
    with pytest.raises(InvalidAmountError):
        check_payment_amount(D("0"), D("60.00"))


def test_credit_note_only_reduces_what_is_unpaid() -> None:
    check_credit_amount(D("10"), D("10"))
    with pytest.raises(InvalidAmountError):
        check_credit_amount(D("10.01"), D("10"))


def test_due_date_limits() -> None:
    check_due_date(TODAY, TODAY)
    check_due_date(TODAY, date(2027, 10, 18))  # 365 days
    with pytest.raises(InvalidAmountError):
        check_due_date(TODAY, date(2026, 10, 17))
    with pytest.raises(InvalidAmountError):
        check_due_date(TODAY, date(2027, 10, 19))


def test_payments_cannot_be_received_in_the_future() -> None:
    check_received_on(TODAY, TODAY)
    with pytest.raises(InvalidAmountError):
        check_received_on(date(2026, 10, 19), TODAY)
