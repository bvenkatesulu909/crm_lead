"""Money arithmetic shared by orders, invoices and credit notes.

Amounts are ``Decimal`` (never float) and are rounded to cents HALF UP (2.345 -> 2.35), per
line, so printed lines always add up to the printed total.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def money(value: Decimal) -> Decimal:
    """Round to cents half up, never banker's rounding."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class LineAmounts:
    subtotal: Decimal
    tax: Decimal
    total: Decimal


def line_amounts(quantity: Decimal, unit_price: Decimal, tax_rate: Decimal) -> LineAmounts:
    subtotal = money(quantity * unit_price)
    tax = money(subtotal * tax_rate / 100)
    return LineAmounts(subtotal, tax, subtotal + tax)


@dataclass(frozen=True)
class Totals:
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal


def totals_of(lines: list[LineAmounts]) -> Totals:
    subtotal = sum((line.subtotal for line in lines), ZERO)
    tax = sum((line.tax for line in lines), ZERO)
    return Totals(subtotal, tax, subtotal + tax)
