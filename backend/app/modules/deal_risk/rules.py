"""Deal risk: pure rules that turn plain signals into a level, a score and reasons (ADR 0037, DR1).

Every point of risk is a listed factor with a code and a plain sentence, so a manager can see WHY a
deal is "high". There is no model and no database here: same signals, same answer.

The score is NOT a probability and is never multiplied into money. A signal that is None means
"not known" (or not readable by the asker): it adds no points and is listed as unknown, so missing
data is never treated as good news.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

RULES_VERSION = 1

# A score at or above these is "medium" / "high". Fixed in v1 (ADR 0037 question 3).
MEDIUM_FROM = 30
HIGH_FROM = 60

OPEN_STAGES = ("prospecting", "qualification", "proposal", "negotiation")
STAGE_ORDER = {stage: i for i, stage in enumerate(OPEN_STAGES)}


@dataclass(frozen=True)
class Signals:
    """What the readers collected for one open deal, as the person asking.

    None = not known / not readable. Counts and days are whole numbers.
    """

    stage: str
    now: datetime
    days_since_last_activity: int | None = None
    overdue_tasks: int | None = None
    has_next_step: bool | None = None
    open_tasks: int | None = None
    expected_close_date: date | None = None
    close_date_pushes: int | None = None  # how many times the date moved later
    days_in_stage: int | None = None
    typical_days_in_stage: int | None = None  # from the organisation's won deals; None = too few
    stage_went_back: bool | None = None
    moved_forward_without_activity: bool | None = None
    quote_state: str | None = None  # none | expired | declined | approval_waiting | ok
    quote_waiting_days: int | None = None
    account_health: str | None = None  # healthy | watch | at_risk
    overdue_invoices: int | None = None
    tickets_past_sla: int | None = None
    contact_count: int | None = None
    has_primary_contact: bool | None = None
    amount: Decimal | None = None
    typical_amount: Decimal | None = None  # the organisation's usual deal; None = unknown
    call_notes_unknown_lines: int | None = None  # ADR 0035; None = no call notes exist


@dataclass(frozen=True)
class Factor:
    code: str
    sentence: str
    points: int
    source: str  # which kind of record it comes from, e.g. "activities"


@dataclass(frozen=True)
class Risk:
    level: str  # low | medium | high
    score: int  # 0-100, higher = more risk; not a probability
    factors: list[Factor] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)  # signals that could not be read
    rules_version: int = RULES_VERSION


def level_for(score: int) -> str:
    return "high" if score >= HIGH_FROM else "medium" if score >= MEDIUM_FROM else "low"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def assess(s: Signals) -> Risk:
    factors: list[Factor] = []
    unknown: list[str] = []

    def add(code: str, sentence: str, points: int, source: str) -> None:
        factors.append(Factor(code, sentence, points, source))

    # --- Touch: when did anything last happen on this deal? ---
    d = s.days_since_last_activity
    if d is None:
        unknown.append("last_activity")
    elif d >= 30:
        add("no_touch_30", f"Nothing has happened on this deal for {d} days", 25, "activities")
    elif d >= 14:
        add("no_touch_14", f"Nothing has happened on this deal for {d} days", 12, "activities")

    # --- Plan: overdue work, or nothing planned at all ---
    if s.overdue_tasks is None:
        unknown.append("tasks")
    elif s.overdue_tasks:
        add(
            "overdue_tasks",
            f"{_plural(s.overdue_tasks, 'follow-up task')} overdue",
            min(5 * s.overdue_tasks, 15),
            "activities",
        )
    if s.has_next_step is False and s.open_tasks == 0:
        add("nothing_planned", "No next step is written and no task is open", 12, "deal")

    # --- Dates ---
    if s.expected_close_date is not None and s.expected_close_date < s.now.date():
        late = (s.now.date() - s.expected_close_date).days
        add(
            "close_date_passed",
            f"The expected close date passed {_plural(late, 'day')} ago",
            20,
            "deal",
        )
    if s.close_date_pushes:
        add(
            "close_date_pushed",
            f"The close date was moved later {_plural(s.close_date_pushes, 'time')}",
            min(6 * s.close_date_pushes, 15),
            "deal",
        )

    # --- Stage ---
    if s.days_in_stage is not None and s.typical_days_in_stage:
        if s.days_in_stage >= 2 * s.typical_days_in_stage:
            add(
                "stuck_in_stage",
                f"In this stage for {s.days_in_stage} days; won deals usually take "
                f"about {s.typical_days_in_stage}",
                15,
                "deal history",
            )
    elif s.days_in_stage is not None:
        unknown.append("typical_stage_time")
    if s.stage_went_back:
        add("stage_went_back", "The deal moved back to an earlier stage", 10, "deal history")
    if s.moved_forward_without_activity:
        add(
            "forward_without_activity",
            "The deal moved forward without any logged activity",
            8,
            "deal history",
        )

    # --- Quote ---
    if s.quote_state == "expired":
        add("quote_expired", "The latest quote has expired", 15, "quotes")
    elif s.quote_state == "declined":
        add("quote_declined", "The latest quote was declined", 20, "quotes")
    elif s.quote_state == "approval_waiting" and (s.quote_waiting_days or 0) >= 5:
        add(
            "quote_stalled",
            f"A discount has been waiting for approval for {s.quote_waiting_days} days",
            10,
            "quotes",
        )
    elif s.stage in ("proposal", "negotiation") and s.quote_state == "none":
        add("no_quote", "The deal is in the proposal stage or later but has no quote", 8, "quotes")

    # --- Account ---
    if s.account_health is None:
        unknown.append("account_health")
    elif s.account_health == "at_risk":
        add("account_at_risk", "The customer account is marked at risk", 12, "account health")
    if s.overdue_invoices:
        add(
            "overdue_invoices",
            f"The account has {_plural(s.overdue_invoices, 'overdue invoice')}",
            8,
            "invoices",
        )
    if s.tickets_past_sla:
        add(
            "tickets_past_sla",
            f"{_plural(s.tickets_past_sla, 'support ticket')} past the service deadline",
            6,
            "tickets",
        )

    # --- People ---
    if s.has_primary_contact is False:
        add("no_primary_contact", "The deal has no primary contact", 8, "contacts")
    elif s.contact_count == 1:
        add("single_threaded", "Only one contact is involved on the buyer's side", 6, "contacts")

    # --- Size: a big deal has more to lose ---
    if s.amount is not None and s.typical_amount and s.amount >= 2 * s.typical_amount:
        add("large_deal", "The amount is at least twice the usual deal size", 5, "deal")

    # --- Call notes (only when they exist; absence is never penalised) ---
    if s.call_notes_unknown_lines and s.call_notes_unknown_lines >= 2:
        add(
            "key_answers_missing",
            f"The last call notes leave {s.call_notes_unknown_lines} checklist lines unanswered",
            6,
            "call notes",
        )

    score = max(0, min(100, sum(f.points for f in factors)))
    return Risk(level=level_for(score), score=score, factors=factors, unknown=unknown)
