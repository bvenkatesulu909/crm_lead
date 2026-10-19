"""Order status flow (money math lives in app.core.money). Pure functions, unit-tested.

Status flow:
    draft ──► confirmed ──► in_fulfilment ──► shipped ──► delivered   (delivered is final)
      │           │               │
      └───────────┴───────────────┴──► cancelled                      (cancelled is final)

- Only drafts can be edited. Confirming freezes the lines and totals.
- Once shipped, an order can no longer be cancelled (that will be a return / credit note).
- Customers never see drafts.
"""

from app.core.errors import ConflictError
from app.core.money import CENT, LineAmounts, line_amounts, money
from app.core.money import Totals as OrderTotals
from app.core.money import totals_of as order_totals

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"confirmed", "cancelled"}),
    "confirmed": frozenset({"in_fulfilment", "shipped", "cancelled"}),
    "in_fulfilment": frozenset({"shipped", "cancelled"}),
    "shipped": frozenset({"delivered"}),
    "delivered": frozenset(),
    "cancelled": frozenset(),
}
# Moving an order through the warehouse needs the "order:fulfil" permission.
FULFILMENT_TARGETS = frozenset({"in_fulfilment", "shipped", "delivered"})
# Cancelling an order that is already being prepared also needs "order:fulfil".
FULFILMENT_STARTED = frozenset({"in_fulfilment"})
FINAL_STATUSES = frozenset({"delivered", "cancelled"})


class InvalidOrderTransitionError(ConflictError):
    code = "invalid_status_transition"


def check_transition(current: str, target: str) -> None:
    if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise InvalidOrderTransitionError(f"An order cannot go from '{current}' to '{target}'.")


__all__ = [
    "CENT",
    "LineAmounts",
    "OrderTotals",
    "line_amounts",
    "money",
    "order_totals",
]
