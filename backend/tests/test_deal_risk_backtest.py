"""Pure tests of the deal risk honesty check (ADR 0037, DR6). No database."""

from datetime import UTC, date, datetime
from decimal import Decimal

from app.modules.deal_risk.backtest import ENOUGH, Case, outcome, summarise

CLOSED = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def case(level: str | None, won: bool, expected: date | None = date(2026, 11, 30)) -> Case:
    return Case(level, won, CLOSED, expected)


def test_outcomes() -> None:
    assert outcome(case("low", won=False)) == "lost"
    assert outcome(case("low", won=True)) == "won_on_time"
    assert outcome(case("low", won=True, expected=date(2026, 11, 20))) == "won_on_time"  # same day
    assert outcome(case("low", won=True, expected=date(2026, 11, 19))) == "won_late"
    assert outcome(case("low", won=True, expected=None)) == "won_on_time"  # no date: not late


def test_rows_count_each_level_and_deals_without_a_forecast() -> None:
    summary = summarise(
        [
            case("high", won=False),
            case("high", won=True, expected=date(2026, 11, 1)),
            case("high", won=True),
            case("low", won=True),
            case(None, won=False),
        ]
    )
    rows = {r.level: r for r in summary.rows}
    assert [r.level for r in summary.rows] == ["high", "medium", "low", "none"]
    high = rows["high"]
    assert (high.deals, high.won_on_time, high.won_late, high.lost) == (3, 1, 1, 1)
    assert high.went_badly == 2 and high.badly_percent == Decimal("66.7")
    assert rows["medium"].deals == 0 and rows["medium"].badly_percent is None
    assert rows["none"].lost == 1
    # Deals without a forecast never count towards "enough".
    assert summary.with_forecast == 4


def test_too_early_until_enough_closed_deals_have_a_forecast() -> None:
    assert ENOUGH == 30
    few = summarise([case("high", won=False)] * 29 + [case(None, won=False)] * 50)
    assert not few.enough and few.verdict.startswith("Too early to measure: 29 of 30")
    assert summarise([case("high", won=False)] * 30).enough


def test_the_verdict_says_whether_high_went_badly_more_often_than_low() -> None:
    good = summarise([case("high", won=False)] * 15 + [case("low", won=True)] * 15)
    assert good.high_beats_low is True and "more often" in good.verdict
    bad = summarise([case("high", won=True)] * 15 + [case("low", won=False)] * 15)
    assert bad.high_beats_low is False and "need revising" in bad.verdict
    same = summarise([case("high", won=False)] * 15 + [case("low", won=False)] * 15)
    assert same.high_beats_low is False  # equal is not better
    no_low = summarise([case("high", won=False)] * 30)
    assert no_low.high_beats_low is None and "Not enough" in no_low.verdict


def test_rates_are_compared_not_raw_counts() -> None:
    # High: 3 of 5 went badly (60 %). Low: 4 of 20 went badly (20 %). By RATE high is worse; by RAW
    # count (3 < 4) it would look better - the verdict must follow the rate.
    summary = summarise(
        [case("high", won=False)] * 3
        + [case("high", won=True)] * 2
        + [case("low", won=False)] * 4
        + [case("low", won=True)] * 16
    )
    assert summary.high_beats_low is True
