"""Pure tests of the deal risk rules (ADR 0037, DR1). No database, no model."""

from datetime import UTC, date, datetime
from decimal import Decimal

from app.modules.deal_risk.rules import HIGH_FROM, MEDIUM_FROM, Signals, assess, level_for

NOW = datetime(2026, 11, 21, 9, 0, tzinfo=UTC)


def sig(**kw: object) -> Signals:
    base: dict[str, object] = {"stage": "proposal", "now": NOW}
    base.update(kw)
    return Signals(**base)  # type: ignore[arg-type]


def codes(**kw: object) -> set[str]:
    return {f.code for f in assess(sig(**kw)).factors}


def test_a_deal_with_nothing_known_scores_zero_and_lists_what_is_unknown() -> None:
    risk = assess(sig())
    assert risk.score == 0 and risk.level == "low" and risk.factors == []
    # Missing data is never good news: it is named, not silently ignored.
    assert {"last_activity", "tasks", "account_health"} <= set(risk.unknown)


def test_touch_thresholds() -> None:
    assert "no_touch_14" not in codes(days_since_last_activity=13)
    assert "no_touch_14" in codes(days_since_last_activity=14)
    assert "no_touch_30" in codes(days_since_last_activity=30)
    assert "no_touch_14" not in codes(days_since_last_activity=30)  # only one of the two


def test_overdue_tasks_points_are_capped() -> None:
    risk = assess(sig(overdue_tasks=9))
    (f,) = [f for f in risk.factors if f.code == "overdue_tasks"]
    assert f.points == 15 and "9 follow-up tasks" in f.sentence


def test_nothing_planned_needs_both_no_next_step_and_no_open_task() -> None:
    assert "nothing_planned" in codes(has_next_step=False, open_tasks=0)
    assert "nothing_planned" not in codes(has_next_step=False, open_tasks=1)
    assert "nothing_planned" not in codes(has_next_step=True, open_tasks=0)
    assert "nothing_planned" not in codes(has_next_step=False)  # open tasks unknown


def test_close_date_passed_and_pushed() -> None:
    assert "close_date_passed" in codes(expected_close_date=date(2026, 11, 20))
    assert "close_date_passed" not in codes(expected_close_date=date(2026, 11, 21))
    risk = assess(sig(close_date_pushes=5))
    (f,) = risk.factors
    assert f.code == "close_date_pushed" and f.points == 15


def test_stuck_in_stage_needs_a_known_typical_time() -> None:
    assert "stuck_in_stage" in codes(days_in_stage=40, typical_days_in_stage=20)
    assert "stuck_in_stage" not in codes(days_in_stage=39, typical_days_in_stage=20)
    risk = assess(sig(days_in_stage=90))  # too few won deals to compare
    assert "stuck_in_stage" not in {f.code for f in risk.factors}
    assert "typical_stage_time" in risk.unknown


def test_stage_movement_factors() -> None:
    assert "stage_went_back" in codes(stage_went_back=True)
    assert "forward_without_activity" in codes(moved_forward_without_activity=True)
    assert not codes(stage_went_back=False, moved_forward_without_activity=False)


def test_quote_factors_are_exclusive() -> None:
    assert codes(quote_state="expired") == {"quote_expired"}
    assert codes(quote_state="declined") == {"quote_declined"}
    assert "quote_stalled" not in codes(quote_state="approval_waiting", quote_waiting_days=4)
    assert "quote_stalled" in codes(quote_state="approval_waiting", quote_waiting_days=5)
    assert "no_quote" in codes(quote_state="none")
    assert "no_quote" not in codes(stage="prospecting", quote_state="none")


def test_account_factors() -> None:
    assert "account_at_risk" in codes(account_health="at_risk")
    assert "account_at_risk" not in codes(account_health="watch")
    assert {"overdue_invoices", "tickets_past_sla"} <= codes(overdue_invoices=1, tickets_past_sla=2)


def test_people_factors() -> None:
    assert "no_primary_contact" in codes(has_primary_contact=False)
    assert "single_threaded" in codes(contact_count=1, has_primary_contact=True)
    assert "single_threaded" not in codes(contact_count=2)


def test_large_deal_is_relative_to_the_usual_size() -> None:
    big = {"amount": Decimal("2000000"), "typical_amount": Decimal("1000000")}
    assert "large_deal" in codes(**big)
    assert "large_deal" not in codes(amount=Decimal("1999999"), typical_amount=Decimal("1000000"))
    assert "large_deal" not in codes(amount=Decimal("2000000"))  # no usual size known


def test_call_notes_are_only_a_signal_when_they_exist() -> None:
    assert "key_answers_missing" in codes(call_notes_unknown_lines=2)
    assert "key_answers_missing" not in codes(call_notes_unknown_lines=1)
    assert "key_answers_missing" not in codes(call_notes_unknown_lines=None)
    assert "key_answers_missing" not in codes(call_notes_unknown_lines=0)


def test_levels_and_clamp() -> None:
    # Literal numbers on purpose: the test must fail if a threshold is changed by accident.
    assert (MEDIUM_FROM, HIGH_FROM) == (30, 60)
    assert level_for(29) == "low"
    assert level_for(30) == "medium"
    assert level_for(59) == "medium"
    assert level_for(60) == "high"
    worst = assess(
        sig(
            days_since_last_activity=90,
            overdue_tasks=5,
            has_next_step=False,
            open_tasks=0,
            expected_close_date=date(2026, 1, 1),
            close_date_pushes=4,
            days_in_stage=100,
            typical_days_in_stage=10,
            stage_went_back=True,
            quote_state="declined",
            account_health="at_risk",
            overdue_invoices=3,
            tickets_past_sla=1,
            has_primary_contact=False,
            amount=Decimal("9"),
            typical_amount=Decimal("1"),
            call_notes_unknown_lines=4,
        )
    )
    assert worst.score == 100 and worst.level == "high"


def test_every_factor_has_a_sentence_a_source_and_positive_points() -> None:
    risk = assess(
        sig(days_since_last_activity=31, overdue_tasks=1, quote_state="declined", contact_count=1)
    )
    assert risk.factors
    for f in risk.factors:
        assert f.sentence and f.source and f.points > 0
    assert risk.score == sum(f.points for f in risk.factors)


def test_same_signals_give_the_same_answer() -> None:
    s = sig(days_since_last_activity=20, overdue_tasks=2)
    assert assess(s) == assess(s)


def test_plain_sentences_use_singular_and_plural() -> None:
    (one,) = assess(sig(overdue_tasks=1)).factors
    assert "1 follow-up task overdue" in one.sentence
