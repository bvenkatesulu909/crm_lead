"""Quote rules: status flow, approval threshold and line money. Pure functions, unit-tested."""

from dataclasses import dataclass
from decimal import Decimal

from app.core.errors import ConflictError
from app.core.money import ZERO, line_amounts, money

# Any line discount ABOVE the organisation's limit needs a manager's approval before the quote
# can be sent. Each organisation can change its limit (quote_settings); this is the default.
DEFAULT_APPROVAL_LIMIT = Decimal("10.00")
DEFAULT_VALIDITY_DAYS = 30

TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"pending_approval", "approved"}),  # submit
    "pending_approval": frozenset({"approved", "draft"}),  # approve / reject
    "approved": frozenset({"sent"}),
    "sent": frozenset({"accepted", "declined"}),
    "accepted": frozenset(),
    "declined": frozenset(),
    "superseded": frozenset(),
}
REVISABLE = frozenset({"pending_approval", "approved", "sent", "declined"})
CUSTOMER_VISIBLE = ("sent", "accepted", "declined")


class QuoteStateError(ConflictError):
    code = "quote_state"


def check_transition(current: str, target: str) -> None:
    if target not in TRANSITIONS.get(current, frozenset()):
        raise QuoteStateError(f"A quote cannot go from '{current}' to '{target}'.")


@dataclass(frozen=True)
class LineMoney:
    net_unit_price: Decimal
    gross: Decimal
    discount: Decimal
    subtotal: Decimal
    tax: Decimal
    total: Decimal


def line_money(
    quantity: Decimal, list_price: Decimal, discount_percent: Decimal, tax_rate: Decimal
) -> LineMoney:
    """Discount is applied to the UNIT price (rounded to cents), so an order made from the
    quote - which only knows unit prices - has exactly the same totals."""
    net_unit = money(list_price * (100 - discount_percent) / 100)
    gross = money(quantity * list_price)
    amounts = line_amounts(quantity, net_unit, tax_rate)
    return LineMoney(
        net_unit_price=net_unit,
        gross=gross,
        discount=gross - amounts.subtotal,
        subtotal=amounts.subtotal,
        tax=amounts.tax,
        total=amounts.total,
    )


@dataclass(frozen=True)
class QuoteMoney:
    gross: Decimal
    discount: Decimal
    subtotal: Decimal
    tax: Decimal
    total: Decimal


def quote_money(lines: list[LineMoney]) -> QuoteMoney:
    def total(attr: str) -> Decimal:
        return sum((getattr(line, attr) for line in lines), ZERO)

    return QuoteMoney(
        total("gross"), total("discount"), total("subtotal"), total("tax"), total("total")
    )


def needs_approval(discounts: list[Decimal], limit: Decimal = DEFAULT_APPROVAL_LIMIT) -> bool:
    return any(d > limit for d in discounts)
