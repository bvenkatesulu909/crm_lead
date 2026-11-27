"""Honesty check on the forecast (ADR 0037, DR6): did deals the CRM called "high risk" really go
badly more often? Pure rules, no database.

For every deal that CLOSED, we take the newest forecast that was made while it was still open and
compare it with what happened:

* **won on time** - won, and closed on or before its expected close date (or it had none);
* **won late** - won, but after its expected close date;
* **lost**.

"Went badly" = lost or won late. A forecast that works shows a clearly higher share of "went badly"
for high than for low. Until the organisation has at least ``ENOUGH`` closed deals with a forecast,
the answer is "too early to measure" (ADR 0037 question 5): a handful of deals proves nothing.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.core.reporting import percent

ENOUGH = 30
LEVELS = ("high", "medium", "low")


@dataclass(frozen=True)
class Case:
    """One closed deal: the level of its last forecast before closing (None = it had none)."""

    level: str | None
    won: bool
    closed_at: datetime
    expected_close_date: date | None


def went_badly(case: Case) -> bool:
    if not case.won:
        return True
    return case.expected_close_date is not None and (
        case.closed_at.date() > case.expected_close_date
    )


def outcome(case: Case) -> str:
    if not case.won:
        return "lost"
    return "won_late" if went_badly(case) else "won_on_time"


@dataclass(frozen=True)
class Row:
    level: str  # high | medium | low | none
    deals: int
    won_on_time: int
    won_late: int
    lost: int

    @property
    def went_badly(self) -> int:
        return self.won_late + self.lost

    @property
    def badly_percent(self) -> Decimal | None:
        return percent(self.went_badly, self.deals)


@dataclass(frozen=True)
class Summary:
    rows: tuple[Row, ...]  # high, medium, low, then deals without a forecast
    with_forecast: int
    enough: bool
    # Only meaningful when enough: high went badly MORE often than low (both need deals).
    high_beats_low: bool | None

    @property
    def verdict(self) -> str:
        if not self.enough:
            return (
                f"Too early to measure: {self.with_forecast} of {ENOUGH} closed deals with a "
                "forecast."
            )
        if self.high_beats_low is None:
            return "Not enough high- and low-risk deals to compare."
        if self.high_beats_low:
            return "High-risk deals went badly more often than low-risk deals."
        return (
            "High-risk deals did NOT go badly more often than low-risk deals: the rules need "
            "revising."
        )


def summarise(cases: list[Case]) -> Summary:
    def row(level: str, members: list[Case]) -> Row:
        kinds = [outcome(c) for c in members]
        return Row(
            level,
            len(members),
            kinds.count("won_on_time"),
            kinds.count("won_late"),
            kinds.count("lost"),
        )

    rows = [row(level, [c for c in cases if c.level == level]) for level in LEVELS]
    rows.append(row("none", [c for c in cases if c.level is None]))
    with_forecast = sum(r.deals for r in rows[:3])
    high, low = rows[0], rows[2]
    comparable = high.deals > 0 and low.deals > 0
    high_beats_low = (
        (high.went_badly * low.deals) > (low.went_badly * high.deals) if comparable else None
    )
    return Summary(tuple(rows), with_forecast, with_forecast >= ENOUGH, high_beats_low)
