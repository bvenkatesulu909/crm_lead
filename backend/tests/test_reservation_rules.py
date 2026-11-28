"""Pure reservation rules (ADR 0040, RP2): amounts, windows, status changes, refunds."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.modules.reservations import rules
from app.modules.reservations.rules import AmountRule, RefundPolicy, ReservationRuleError

T0 = datetime(2026, 11, 27, 10, 0, tzinfo=UTC)
D = Decimal


def fixed(amount: str = "100000", lo: str = "50000", hi: str = "500000") -> AmountRule:
    return AmountRule("fixed", D(amount), None, D(lo), D(hi))


def pct(percent: str = "2", lo: str = "50000", hi: str = "500000") -> AmountRule:
    return AmountRule("percent", None, D(percent), D(lo), D(hi))


POLICY = RefundPolicy(free_cancel_hours=48, kept_percent=D("10"))


# --- token amount -------------------------------------------------------------------------


def test_a_fixed_token_is_that_amount() -> None:
    assert rules.token_amount(fixed(), D("4500000")) == D("100000")


def test_a_percentage_token_is_rounded_half_up_to_whole_rupees() -> None:
    # 2 % of 4,500,025.25 = 90,000.505 -> 90,001
    assert rules.token_amount(pct("2"), D("4500025.25")) == D("90001")
    # 2 % of 4,500,024.75 = 90,000.495 -> 90,000
    assert rules.token_amount(pct("2"), D("4500024.75")) == D("90000")


def test_a_percentage_below_the_minimum_is_raised_to_it() -> None:
    assert rules.token_amount(pct("1"), D("1000000")) == D("50000")


def test_a_percentage_above_the_maximum_is_cut_to_it() -> None:
    assert rules.token_amount(pct("10"), D("90000000")) == D("500000")


def test_the_token_is_never_above_the_price() -> None:
    assert rules.token_amount(fixed("100000", "50000", "500000"), D("60000")) == D("60000")


def test_the_result_is_a_decimal_never_a_float() -> None:
    assert isinstance(rules.token_amount(pct("2.5"), D("3333333")), Decimal)


@pytest.mark.parametrize("price", [D("0"), D("-1")])
def test_a_unit_without_a_price_cannot_be_reserved(price: Decimal) -> None:
    with pytest.raises(ReservationRuleError) as e:
        rules.token_amount(fixed(), price)
    assert e.value.code == "price_not_positive"


@pytest.mark.parametrize(
    ("rule", "code"),
    [
        (AmountRule("weekly", None, None, D("1"), D("2")), "amount_mode_unknown"),
        (AmountRule("fixed", D("5"), None, D("0"), D("10")), "amount_min_not_positive"),
        (AmountRule("fixed", D("5"), None, D("10"), D("1")), "amount_range_inverted"),
        (AmountRule("fixed", None, None, D("1"), D("10")), "amount_fixed_needs_amount"),
        (AmountRule("fixed", D("5"), D("2"), D("1"), D("10")), "amount_fixed_needs_amount"),
        (AmountRule("fixed", D("50"), None, D("1"), D("10")), "amount_fixed_out_of_range"),
        (AmountRule("percent", None, None, D("1"), D("10")), "amount_percent_needs_percent"),
        (AmountRule("percent", D("5"), D("2"), D("1"), D("10")), "amount_percent_needs_percent"),
        (AmountRule("percent", None, D("0"), D("1"), D("10")), "amount_percent_out_of_range"),
        (AmountRule("percent", None, D("100.01"), D("1"), D("10")), "amount_percent_out_of_range"),
    ],
)
def test_broken_rules_are_refused_with_a_code(rule: AmountRule, code: str) -> None:
    with pytest.raises(ReservationRuleError) as e:
        rules.check_amount_rule(rule)
    assert e.value.code == code


def test_an_amount_outside_the_limits_needs_a_managers_exception() -> None:
    rule = fixed()
    assert not rules.needs_exception(rule, D("50000"))
    assert not rules.needs_exception(rule, D("500000"))
    assert rules.needs_exception(rule, D("49999.99"))
    assert rules.needs_exception(rule, D("500000.01"))


# --- windows ------------------------------------------------------------------------------


def test_the_buyer_has_24_hours_to_pay_and_the_hold_is_7_days() -> None:
    assert rules.payment_due_at(T0) == T0 + timedelta(hours=24)
    assert rules.held_until(T0) == T0 + timedelta(days=7)


def test_an_unpaid_reservation_reads_as_expired_after_its_window() -> None:
    due = rules.payment_due_at(T0)
    assert rules.effective_status("pending_payment", due_at=due, until=None, now=due) == (
        "pending_payment"
    )
    later = due + timedelta(seconds=1)
    assert rules.effective_status("pending_payment", due_at=due, until=None, now=later) == "expired"


def test_a_lapsed_hold_reads_as_refund_due_even_before_the_worker_runs() -> None:
    until = rules.held_until(T0)
    due = rules.payment_due_at(T0)
    assert rules.effective_status("held", due_at=due, until=until, now=until) == "held"
    after = until + timedelta(seconds=1)
    assert rules.effective_status("held", due_at=due, until=until, now=after) == "refund_due"


@pytest.mark.parametrize("status", ["converted", "refunded", "cancelled", "refund_due"])
def test_finished_statuses_are_not_changed_by_time(status: str) -> None:
    far = T0 + timedelta(days=400)
    assert rules.effective_status(status, due_at=T0, until=T0, now=far) == status


# --- status changes -----------------------------------------------------------------------


ALLOWED = {
    ("pending_payment", "held"),
    ("pending_payment", "expired"),
    ("pending_payment", "cancelled"),
    ("pending_payment", "refund_due"),
    ("held", "converted"),
    ("held", "refund_due"),
    ("expired", "refund_due"),
    ("cancelled", "refund_due"),
    ("refund_due", "refunded"),
}


@pytest.mark.parametrize("old", rules.STATUSES)
@pytest.mark.parametrize("new", rules.STATUSES)
def test_only_the_listed_status_changes_are_allowed(old: str, new: str) -> None:
    assert rules.can_change(old, new) == ((old, new) in ALLOWED)
    if (old, new) not in ALLOWED:
        with pytest.raises(ReservationRuleError) as e:
            rules.require_change(old, new)
        assert e.value.code == "status_change_not_allowed"


def test_a_held_unit_can_never_be_released_back_to_waiting_for_payment() -> None:
    assert not rules.can_change("held", "pending_payment")
    assert not rules.can_change("held", "expired")  # paid money is owed back, not forgotten


# --- payments -----------------------------------------------------------------------------


def test_a_payment_in_time_holds_the_unit() -> None:
    due = rules.payment_due_at(T0)
    out = rules.on_payment("pending_payment", due_at=due, paid_at=due, unit_free=True)
    assert (out.status, out.refund_reason) == ("held", None)


def test_a_late_payment_never_reserves_and_is_owed_back() -> None:
    due = rules.payment_due_at(T0)
    late = due + timedelta(seconds=1)
    for status in ("pending_payment", "expired", "cancelled"):
        out = rules.on_payment(status, due_at=due, paid_at=late, unit_free=True)
        assert (out.status, out.refund_reason) == ("refund_due", "late_payment"), status


def test_money_for_a_unit_someone_else_took_is_owed_back() -> None:
    due = rules.payment_due_at(T0)
    out = rules.on_payment("pending_payment", due_at=due, paid_at=T0, unit_free=False)
    assert (out.status, out.refund_reason) == ("refund_due", "unit_taken")


@pytest.mark.parametrize("status", ["held", "converted", "refund_due", "refunded"])
def test_a_repeated_payment_notice_changes_nothing(status: str) -> None:
    out = rules.on_payment(status, due_at=T0, paid_at=T0, unit_free=True)
    assert (out.status, out.refund_reason) == (None, None)


# --- refunds ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reason", ["late_payment", "unit_taken", "seller_cancelled", "unit_withdrawn"]
)
def test_these_reasons_repay_everything_whenever_they_happen(reason: str) -> None:
    long_after = T0 + timedelta(days=30)
    got = rules.refund_amount(D("100000"), reason=reason, policy=POLICY, paid_at=T0, at=long_after)
    assert got == D("100000.00")


def test_a_buyer_cancelling_in_the_free_window_gets_everything_back() -> None:
    edge = T0 + timedelta(hours=48)
    got = rules.refund_amount(
        D("100000"), reason="buyer_cancelled", policy=POLICY, paid_at=T0, at=edge
    )
    assert got == D("100000.00")


def test_after_the_free_window_the_kept_part_is_taken_off_to_the_paise() -> None:
    after = T0 + timedelta(hours=48, seconds=1)
    got = rules.refund_amount(
        D("33333.33"), reason="buyer_cancelled", policy=POLICY, paid_at=T0, at=after
    )
    assert got == D("30000.00")  # 33,333.33 x 0.9 = 29,999.997 -> 30,000.00
    lapsed = rules.refund_amount(
        D("100000"), reason="hold_lapsed", policy=POLICY, paid_at=T0, at=after
    )
    assert lapsed == D("90000.00")


def test_a_refund_is_never_more_than_was_paid_or_below_zero() -> None:
    after = T0 + timedelta(days=10)
    keep_all = RefundPolicy(free_cancel_hours=0, kept_percent=D("100"))
    assert rules.refund_amount(
        D("5000"), reason="buyer_cancelled", policy=keep_all, paid_at=T0, at=after
    ) == D("0.00")
    keep_none = RefundPolicy(free_cancel_hours=0, kept_percent=D("0"))
    assert rules.refund_amount(
        D("5000"), reason="buyer_cancelled", policy=keep_none, paid_at=T0, at=after
    ) == D("5000.00")


@pytest.mark.parametrize(
    ("policy", "code"),
    [
        (RefundPolicy(-1, D("10")), "free_cancel_out_of_range"),
        (RefundPolicy(721, D("10")), "free_cancel_out_of_range"),
        (RefundPolicy(24, D("-0.01")), "kept_percent_out_of_range"),
        (RefundPolicy(24, D("100.01")), "kept_percent_out_of_range"),
    ],
)
def test_broken_refund_policies_are_refused(policy: RefundPolicy, code: str) -> None:
    with pytest.raises(ReservationRuleError) as e:
        rules.check_refund_policy(policy)
    assert e.value.code == code


def test_an_unknown_reason_or_nothing_paid_is_refused() -> None:
    with pytest.raises(ReservationRuleError) as e:
        rules.refund_amount(D("10"), reason="because", policy=POLICY, paid_at=T0, at=T0)
    assert e.value.code == "refund_reason_unknown"
    with pytest.raises(ReservationRuleError) as e:
        rules.refund_amount(D("0"), reason="late_payment", policy=POLICY, paid_at=T0, at=T0)
    assert e.value.code == "amount_not_positive"
