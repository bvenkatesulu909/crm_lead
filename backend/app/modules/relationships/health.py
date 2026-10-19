"""Customer health: a transparent 0-100 score built from real signals.

Every point deducted or added is listed as a factor, so a user can see WHY a customer is
"at risk" - nothing is hidden in a model. Weights are deliberately simple and documented in
docs/customer-relationships.md; they can be tuned per organisation in the administration phase.
"""

from dataclasses import dataclass, field
from datetime import datetime

INACTIVE_AFTER_DAYS = 90  # "inactive account" indicator
HEALTHY_FROM = 75
WATCH_FROM = 50


@dataclass(frozen=True)
class Signals:
    last_interaction_at: datetime | None  # activities, orders, tickets - whichever is latest
    overdue_invoices: int = 0
    sla_overdue_tickets: int = 0
    open_complaints: int = 0
    average_rating: float | None = None
    won_deals_last_year: int = 0
    lifecycle_stage: str | None = None


@dataclass(frozen=True)
class Factor:
    label: str
    impact: int  # points added (+) or deducted (-)


@dataclass(frozen=True)
class Health:
    score: int
    label: str  # healthy | watch | at_risk
    days_inactive: int | None
    inactive: bool
    factors: list[Factor] = field(default_factory=list)


def assess(signals: Signals, now: datetime) -> Health:
    factors: list[Factor] = []
    days: int | None = None
    if signals.last_interaction_at is None:
        factors.append(Factor("No recorded interaction yet", -20))
    else:
        days = max((now - signals.last_interaction_at).days, 0)
        if days >= 180:
            factors.append(Factor(f"No interaction for {days} days", -45))
        elif days >= INACTIVE_AFTER_DAYS:
            factors.append(Factor(f"No interaction for {days} days", -30))
        elif days >= 30:
            factors.append(Factor(f"Last interaction {days} days ago", -10))
    if signals.overdue_invoices:
        n = signals.overdue_invoices
        factors.append(Factor(f"{n} overdue invoice{'s' if n > 1 else ''}", -min(10 * n, 30)))
    if signals.sla_overdue_tickets:
        factors.append(Factor(f"{signals.sla_overdue_tickets} support ticket(s) past SLA", -15))
    if signals.open_complaints:
        factors.append(Factor(f"{signals.open_complaints} open complaint(s)", -10))
    if signals.average_rating is not None and signals.average_rating < 3:
        factors.append(Factor(f"Low satisfaction ({signals.average_rating:.1f} of 5)", -10))
    if signals.average_rating is not None and signals.average_rating >= 4.5:
        factors.append(Factor(f"High satisfaction ({signals.average_rating:.1f} of 5)", 5))
    if signals.won_deals_last_year:
        factors.append(Factor(f"{signals.won_deals_last_year} deal(s) won in the last year", 5))
    if signals.lifecycle_stage == "churned":
        factors.append(Factor("Marked as churned", -40))

    score = max(0, min(100, 100 + sum(f.impact for f in factors)))
    label = "healthy" if score >= HEALTHY_FROM else "watch" if score >= WATCH_FROM else "at_risk"
    return Health(
        score=score,
        label=label,
        days_inactive=days,
        inactive=days is None or days >= INACTIVE_AFTER_DAYS,
        factors=factors,
    )
