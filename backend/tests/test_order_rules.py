"""Order status flow and money calculations (pure functions, no database)."""

from decimal import Decimal

import pytest

from app.modules.orders.rules import (
    ALLOWED_TRANSITIONS,
    InvalidOrderTransitionError,
    check_transition,
    line_amounts,
    money,
    order_totals,
)

D = Decimal


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("draft", "confirmed"),
        ("draft", "cancelled"),
        ("confirmed", "in_fulfilment"),
        ("confirmed", "shipped"),
        ("confirmed", "cancelled"),
        ("in_fulfilment", "shipped"),
        ("in_fulfilment", "cancelled"),
        ("shipped", "delivered"),
    ],
)
def test_allowed_transitions(current: str, target: str) -> None:
    check_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("draft", "shipped"),  # must be confirmed first
        ("draft", "delivered"),
        ("confirmed", "draft"),  # confirmed orders never go back to editable
        ("shipped", "cancelled"),  # too late: that is a return
        ("delivered", "cancelled"),
        ("cancelled", "confirmed"),  # final
        ("delivered", "shipped"),  # final
        ("shipped", "shipped"),
    ],
)
def test_forbidden_transitions(current: str, target: str) -> None:
    with pytest.raises(InvalidOrderTransitionError):
        check_transition(current, target)


def test_final_statuses_have_no_way_out() -> None:
    assert ALLOWED_TRANSITIONS["delivered"] == frozenset()
    assert ALLOWED_TRANSITIONS["cancelled"] == frozenset()


def test_money_rounds_half_up_not_bankers() -> None:
    assert money(D("2.345")) == D("2.35")
    assert money(D("2.125")) == D("2.13")  # banker's rounding would give 2.12
    assert money(D("2.3449")) == D("2.34")


def test_line_amounts() -> None:
    line = line_amounts(D("3"), D("19.99"), D("19"))
    assert (line.subtotal, line.tax, line.total) == (D("59.97"), D("11.39"), D("71.36"))


def test_fractional_quantity_and_zero_tax() -> None:
    line = line_amounts(D("2.5"), D("10.01"), D("0"))
    assert (line.subtotal, line.tax, line.total) == (D("25.03"), D("0.00"), D("25.03"))


def test_no_float_error() -> None:
    # 0.1 + 0.2 != 0.3 in floating point; with Decimal it is exact.
    line = line_amounts(D("3"), D("0.10"), D("0"))
    assert line.total == D("0.30")


def test_order_totals_add_up_the_rounded_lines() -> None:
    lines = [line_amounts(D("1"), D("0.05"), D("50")), line_amounts(D("1"), D("0.05"), D("50"))]
    totals = order_totals(lines)
    # Each line's tax 0.025 rounds to 0.03, so the order tax is 0.06 (not round(0.05) = 0.05):
    # the printed lines always add up to the printed total.
    assert (totals.subtotal, totals.tax_total, totals.total) == (D("0.10"), D("0.06"), D("0.16"))


def test_empty_order_totals_are_zero() -> None:
    totals = order_totals([])
    assert (totals.subtotal, totals.tax_total, totals.total) == (D("0"), D("0"), D("0"))
