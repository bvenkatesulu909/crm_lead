"""Quote money, approval and status rules (no database)."""

from decimal import Decimal

import pytest

from app.modules.quotes.rules import (
    QuoteStateError,
    check_transition,
    line_money,
    needs_approval,
    quote_money,
)

D = Decimal


def test_discount_is_applied_to_the_unit_price() -> None:
    line = line_money(D("3"), D("100.00"), D("15"), D("19"))
    assert (line.net_unit_price, line.gross, line.discount) == (D("85.00"), D("300.00"), D("45.00"))
    assert (line.subtotal, line.tax, line.total) == (D("255.00"), D("48.45"), D("303.45"))


def test_rounding_is_per_unit_then_per_line_half_up() -> None:
    line = line_money(D("3"), D("19.99"), D("12.5"), D("0"))
    # 19.99 * 0.875 = 17.49125 -> 17.49; 3 * 17.49 = 52.47; gross 59.97
    assert (line.net_unit_price, line.subtotal, line.discount) == (
        D("17.49"),
        D("52.47"),
        D("7.50"),
    )
    half = line_money(D("1"), D("0.05"), D("50"), D("0"))
    assert half.net_unit_price == D("0.03")  # 0.025 rounds HALF UP, not to even


def test_quote_totals_add_up_lines() -> None:
    lines = [
        line_money(D("3"), D("100"), D("15"), D("19")),
        line_money(D("1.5"), D("80"), D("0"), D("19")),
    ]
    totals = quote_money(lines)
    assert (totals.gross, totals.discount, totals.subtotal) == (
        D("420.00"),
        D("45.00"),
        D("375.00"),
    )
    assert (totals.tax, totals.total) == (D("71.25"), D("446.25"))
    empty = quote_money([])
    assert (empty.total, empty.discount) == (D("0.00"), D("0.00"))


@pytest.mark.parametrize(
    ("discounts", "expected"),
    [([], False), ([D("0"), D("10")], False), ([D("10.01")], True), ([D("5"), D("50")], True)],
)
def test_approval_needed_only_above_ten_percent(discounts: list[Decimal], expected: bool) -> None:
    assert needs_approval(discounts) is expected


@pytest.mark.parametrize(
    ("current", "target"),
    [("draft", "sent"), ("pending_approval", "sent"), ("sent", "draft"), ("accepted", "declined"),
     ("superseded", "draft"), ("declined", "accepted")],
)  # fmt: skip
def test_forbidden_transitions(current: str, target: str) -> None:
    with pytest.raises(QuoteStateError):
        check_transition(current, target)
