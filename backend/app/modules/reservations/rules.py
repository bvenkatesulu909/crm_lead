"""Pure rules for reserving a unit with a token amount (ADR 0040, RP2). No database, no clock.

The owner's decisions (ADR 0040 section 6a) are written here as constants, not settings:

- the buyer has **24 hours** to pay the token (the payment window);
- once paid, the unit is **held for 7 days** (fixed, not editable);
- money that arrives late, or for a unit someone else has meanwhile reserved, becomes
  **refund due** - it never reserves anything by itself;
- the token amount is a fixed amount or a percentage of the price, kept between the
  organisation's **minimum and maximum** (anything else is an exception a manager approves).

Money is ``Decimal`` everywhere; nothing here moves money - a refund is recorded by a person.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

PAYMENT_WINDOW = timedelta(hours=24)
HOLD_PERIOD = timedelta(days=7)

STATUSES = (
    "pending_payment",
    "held",
    "expired",
    "cancelled",
    "converted",
    "refund_due",
    "refunded",
)
# A unit is taken while one of its reservations is in one of these.
ACTIVE_STATUSES = ("pending_payment", "held")

# Every allowed change of status. Anything else is refused here and by the database.
TRANSITIONS: dict[str, frozenset[str]] = {
    "pending_payment": frozenset({"held", "expired", "cancelled", "refund_due"}),
    "held": frozenset({"converted", "refund_due"}),
    "expired": frozenset({"refund_due"}),
    "cancelled": frozenset({"refund_due"}),
    "refund_due": frozenset({"refunded"}),
    "converted": frozenset(),
    "refunded": frozenset(),
}

# Why money is owed back. The first four repay everything; the last two follow the policy.
REFUND_REASONS = (
    "late_payment",
    "unit_taken",
    "seller_cancelled",
    "unit_withdrawn",
    "buyer_cancelled",
    "hold_lapsed",
)
_FULL_REFUND = frozenset({"late_payment", "unit_taken", "seller_cancelled", "unit_withdrawn"})

AMOUNT_MODES = ("fixed", "percent")
MAX_FREE_CANCEL_HOURS = 720  # 30 days
RUPEE = Decimal("1")
PAISE = Decimal("0.01")


class ReservationRuleError(ValueError):
    """A rule was broken; ``code`` is stable and shown to the API later."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AmountRule:
    """One version of an organisation's token rule."""

    mode: str
    fixed_amount: Decimal | None
    percent: Decimal | None
    min_amount: Decimal
    max_amount: Decimal


@dataclass(frozen=True)
class RefundPolicy:
    """How much of a paid token a buyer gets back when they cancel."""

    free_cancel_hours: int
    kept_percent: Decimal


def check_amount_rule(rule: AmountRule) -> None:
    if rule.mode not in AMOUNT_MODES:
        raise ReservationRuleError("amount_mode_unknown", "Choose a fixed amount or a percentage.")
    if rule.min_amount <= 0:
        raise ReservationRuleError("amount_min_not_positive", "The minimum must be above zero.")
    if rule.min_amount > rule.max_amount:
        raise ReservationRuleError("amount_range_inverted", "The minimum is above the maximum.")
    if rule.mode == "fixed":
        if rule.fixed_amount is None or rule.percent is not None:
            raise ReservationRuleError("amount_fixed_needs_amount", "Give one fixed amount.")
        if not rule.min_amount <= rule.fixed_amount <= rule.max_amount:
            raise ReservationRuleError(
                "amount_fixed_out_of_range", "The fixed amount must be between the limits."
            )
    else:
        if rule.percent is None or rule.fixed_amount is not None:
            raise ReservationRuleError("amount_percent_needs_percent", "Give one percentage.")
        if not Decimal("0") < rule.percent <= Decimal("100"):
            raise ReservationRuleError(
                "amount_percent_out_of_range", "The percentage must be above 0 and at most 100."
            )


def check_refund_policy(policy: RefundPolicy) -> None:
    if not 0 <= policy.free_cancel_hours <= MAX_FREE_CANCEL_HOURS:
        raise ReservationRuleError(
            "free_cancel_out_of_range", "The free cancellation time must be 0 to 720 hours."
        )
    if not Decimal("0") <= policy.kept_percent <= Decimal("100"):
        raise ReservationRuleError(
            "kept_percent_out_of_range", "The part kept must be between 0 and 100 percent."
        )


def token_amount(rule: AmountRule, price: Decimal) -> Decimal:
    """The token for a unit at ``price``: the rule, kept within the limits, never above the price.

    Rounded half-up to whole rupees, because a token is quoted to buyers in whole rupees.
    """
    check_amount_rule(rule)
    if price <= 0:
        raise ReservationRuleError("price_not_positive", "This unit has no price to reserve at.")
    if rule.mode == "fixed" and rule.fixed_amount is not None:
        raw = rule.fixed_amount
    elif rule.percent is not None:
        raw = price * rule.percent / Decimal("100")
    else:  # check_amount_rule already refuses this; kept so the type checker can see it
        raise ReservationRuleError("amount_rule_incomplete", "The token rule is incomplete.")
    bounded = min(max(raw, rule.min_amount), rule.max_amount)
    amount = min(bounded, price).quantize(RUPEE, rounding=ROUND_HALF_UP)
    if amount <= 0:
        raise ReservationRuleError("amount_not_positive", "The token would be zero.")
    return amount


def needs_exception(rule: AmountRule, amount: Decimal) -> bool:
    """A person asking for a different amount outside the limits needs a manager's approval."""
    return not rule.min_amount <= amount <= rule.max_amount


def payment_due_at(created_at: datetime) -> datetime:
    return created_at + PAYMENT_WINDOW


def held_until(paid_at: datetime) -> datetime:
    return paid_at + HOLD_PERIOD


def can_change(current: str, new: str) -> bool:
    return new in TRANSITIONS.get(current, frozenset())


def require_change(current: str, new: str) -> None:
    if not can_change(current, new):
        raise ReservationRuleError(
            "status_change_not_allowed", f"A reservation cannot go from {current} to {new}."
        )


def effective_status(
    status: str, *, due_at: datetime, until: datetime | None, now: datetime
) -> str:
    """What the status is NOW, even if the worker has not swept yet (ADR 0040 RP4).

    An unpaid reservation past its window reads as ``expired``; a hold past its end reads as
    ``refund_due`` (the money is owed back under the policy). Nothing is written here.
    """
    if status == "pending_payment" and now > due_at:
        return "expired"
    if status == "held" and until is not None and now > until:
        return "refund_due"
    return status


@dataclass(frozen=True)
class PaymentOutcome:
    status: str | None  # None = nothing changes (a repeated payment notice)
    refund_reason: str | None


def on_payment(
    status: str, *, due_at: datetime, paid_at: datetime, unit_free: bool
) -> PaymentOutcome:
    """What a recorded payment does. Money is never silently turned into a reservation."""
    if status == "pending_payment":
        if paid_at > due_at:
            return PaymentOutcome("refund_due", "late_payment")
        if not unit_free:
            return PaymentOutcome("refund_due", "unit_taken")
        return PaymentOutcome("held", None)
    if status in ("expired", "cancelled"):
        return PaymentOutcome("refund_due", "late_payment")
    return PaymentOutcome(None, None)


def refund_amount(
    amount: Decimal,
    *,
    reason: str,
    policy: RefundPolicy,
    paid_at: datetime,
    at: datetime,
) -> Decimal:
    """How much is owed back, to the paise. Never more than was paid, never below zero."""
    if reason not in REFUND_REASONS:
        raise ReservationRuleError("refund_reason_unknown", "Unknown reason for a refund.")
    check_refund_policy(policy)
    if amount <= 0:
        raise ReservationRuleError("amount_not_positive", "Nothing was paid.")
    if reason in _FULL_REFUND:
        return amount.quantize(PAISE, rounding=ROUND_HALF_UP)
    if at <= paid_at + timedelta(hours=policy.free_cancel_hours):
        return amount.quantize(PAISE, rounding=ROUND_HALF_UP)
    back = amount * (Decimal("100") - policy.kept_percent) / Decimal("100")
    return back.quantize(PAISE, rounding=ROUND_HALF_UP)
