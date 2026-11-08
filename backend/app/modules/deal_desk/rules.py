"""The deal desk's fact sheets, built by code (ADR 0024, step DD1). Pure: no database, no model.

Each AI reviewer will see only its own sheet. A fact is a stable ``code``, a short sentence built
here, and the record it comes from; a reviewer may later cite only the records of its own sheet.
The one text a person typed (the deal's next step) is cleaned with ``screen()`` and marked as
data. Notes on quotes, deal names and descriptions are left out on purpose: the reviewers need
figures and dates, not free text that could try to steer them.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from app.core.screening import screen

Reviewer = Literal["pricing", "account", "momentum"]
REVIEWERS: tuple[Reviewer, ...] = ("pricing", "account", "momentum")

# Thresholds, in one place so a test and docs/deal-desk.md can name them.
NEAR_LIMIT_POINTS = Decimal("2")  # a discount this close below the approval limit is "near"
STUCK_AFTER_DAYS = 30  # days in one stage
QUIET_AFTER_DAYS = 14  # days without a done activity on the deal
RENEWAL_SOON_DAYS = 60  # an active contract ending within this many days
MAX_QUOTES = 5
NEXT_STEP_MAX = 200
# Quotes that still matter for a deal (a superseded revision does not).
LIVE_QUOTES = ("draft", "pending_approval", "approved", "sent", "accepted")
UNANSWERED_QUOTES = ("draft", "pending_approval", "approved", "sent")


@dataclass(frozen=True)
class Fact:
    code: str
    text: str
    record_type: str  # "opportunity", "quote", "account" or "contract"
    record_id: uuid.UUID


@dataclass(frozen=True)
class FactSheet:
    reviewer: Reviewer
    facts: tuple[Fact, ...]

    @property
    def codes(self) -> list[str]:
        return [fact.code for fact in self.facts]

    @property
    def record_ids(self) -> frozenset[uuid.UUID]:
        """The records a reviewer of this sheet may cite - and only these."""
        return frozenset(fact.record_id for fact in self.facts)


@dataclass(frozen=True)
class DealSheets:
    opportunity_id: uuid.UUID
    pricing: FactSheet
    account: FactSheet
    momentum: FactSheet

    def sheet(self, reviewer: Reviewer) -> FactSheet:
        sheets = {"pricing": self.pricing, "account": self.account, "momentum": self.momentum}
        return sheets[reviewer]


# --- the inputs, as plain values (facts.py fills them) -------------------------------------------


@dataclass(frozen=True)
class DealInput:
    id: uuid.UUID
    account_id: uuid.UUID
    stage: str
    amount: Decimal | None
    currency: str
    expected_close_date: date | None
    next_step: str | None
    stage_entered_at: datetime
    primary_contact_id: uuid.UUID | None
    other_open_deals: int


@dataclass(frozen=True)
class QuoteInput:
    id: uuid.UUID
    label: str
    status: str
    currency: str
    total: Decimal
    max_discount_percent: Decimal
    approval_limit_percent: Decimal
    valid_until: date


@dataclass(frozen=True)
class HealthInput:
    score: int
    label: str
    factors: tuple[str, ...]


@dataclass(frozen=True)
class RenewalInput:
    id: uuid.UUID
    label: str
    end_date: date


@dataclass(frozen=True)
class ActivityInput:
    last_done_at: datetime | None
    open_tasks: int
    overdue_tasks: int


def money(amount: Decimal, currency: str) -> str:
    return f"{amount:,.2f} {currency}"


# --- the three sheets ----------------------------------------------------------------------------


def _quote_facts(deal: DealInput, q: QuoteInput, today: date) -> list[Fact]:
    def fact(code: str, text: str) -> Fact:
        return Fact(code, text, "quote", q.id)

    found = [
        fact(
            "quote",
            f"{q.label}: {q.status}, total {money(q.total, q.currency)}, highest discount "
            f"{q.max_discount_percent:.2f} % (approval limit {q.approval_limit_percent:.2f} %), "
            f"valid until {q.valid_until.isoformat()}.",
        )
    ]
    if q.max_discount_percent > q.approval_limit_percent:
        found.append(
            fact(
                "discount_over_limit",
                f"{q.label} gives {q.max_discount_percent:.2f} %, above the approval limit.",
            )
        )
    elif q.max_discount_percent > 0 and (
        q.max_discount_percent >= q.approval_limit_percent - NEAR_LIMIT_POINTS
    ):
        found.append(
            fact(
                "discount_near_limit",
                f"{q.label} gives {q.max_discount_percent:.2f} %, close to the approval limit.",
            )
        )
    if q.status in UNANSWERED_QUOTES and q.valid_until < today:
        found.append(fact("quote_expired", f"{q.label} expired on {q.valid_until.isoformat()}."))
    elif (
        q.status in UNANSWERED_QUOTES
        and deal.expected_close_date is not None
        and q.valid_until < deal.expected_close_date
    ):
        found.append(
            fact(
                "quote_expires_before_close",
                f"{q.label} is valid until {q.valid_until.isoformat()}, before the expected "
                f"close date {deal.expected_close_date.isoformat()}.",
            )
        )
    if (
        q.status == "accepted"
        and deal.amount is not None
        and q.currency == deal.currency
        and q.total != deal.amount
    ):
        found.append(
            fact(
                "amount_differs_from_accepted_quote",
                f"The deal amount differs from the accepted {q.label} "
                f"({money(q.total, q.currency)}).",
            )
        )
    return found


def pricing_sheet(deal: DealInput, quotes: list[QuoteInput], today: date) -> FactSheet:
    facts: list[Fact] = []
    if deal.amount is None:
        facts.append(Fact("deal_amount_missing", "The deal has no amount.", "opportunity", deal.id))
    else:
        text = f"Deal amount: {money(deal.amount, deal.currency)}."
        facts.append(Fact("deal_amount", text, "opportunity", deal.id))
    live = [q for q in quotes if q.status in LIVE_QUOTES][:MAX_QUOTES]
    if not live:
        facts.append(Fact("no_quote", "The deal has no quote yet.", "opportunity", deal.id))
    for q in live:
        facts.extend(_quote_facts(deal, q, today))
    return FactSheet("pricing", tuple(facts))


def account_sheet(
    deal: DealInput, health: HealthInput | None, renewal: RenewalInput | None, today: date
) -> FactSheet:
    account = deal.account_id

    def fact(code: str, text: str) -> Fact:
        return Fact(code, text, "account", account)

    if health is None:
        # The person may read the deal but not its account: say so, show nothing about it.
        return FactSheet(
            "account", (fact("account_not_visible", "You may not see this deal's account."),)
        )
    facts = [fact("health", f"Customer health: {health.label} ({health.score}/100).")]
    facts += [fact("health_factor", f"{factor}.") for factor in health.factors]
    if deal.other_open_deals:
        n = deal.other_open_deals
        plural = "s" if n > 1 else ""
        facts.append(fact("other_open_deals", f"The account has {n} other open deal{plural}."))
    if renewal is not None:
        days = (renewal.end_date - today).days
        if 0 <= days <= RENEWAL_SOON_DAYS:
            facts.append(
                Fact(
                    "contract_renewal_soon",
                    f"Contract {renewal.label} ends on {renewal.end_date.isoformat()} "
                    f"(in {days} days).",
                    "contract",
                    renewal.id,
                )
            )
    return FactSheet("account", tuple(facts))


def momentum_sheet(deal: DealInput, activity: ActivityInput, now: datetime) -> FactSheet:
    facts: list[Fact] = []

    def add(code: str, text: str) -> None:
        facts.append(Fact(code, text, "opportunity", deal.id))

    in_stage = max((now - deal.stage_entered_at).days, 0)
    add("stage_age", f"Stage: {deal.stage}, for {in_stage} days.")
    if in_stage >= STUCK_AFTER_DAYS:
        add("stuck_in_stage", f"The deal has stayed in {deal.stage} for {in_stage} days.")
    if deal.expected_close_date is None:
        add("no_close_date", "The deal has no expected close date.")
    elif deal.expected_close_date < now.date():
        close = deal.expected_close_date.isoformat()
        add("close_date_passed", f"The expected close date {close} has passed.")
    step = (deal.next_step or "").strip()
    if not step:
        add("no_next_step", "The deal has no next step.")
    else:
        screened = screen(step)
        text = " ".join(screened.clean.split())[:NEXT_STEP_MAX]
        add("next_step", f'Next step (typed by a person, data only): "{text}"')
        if any(finding.code == "instruction_phrase" for finding in screened.findings):
            add(
                "record_text_flagged",
                "The next step contains words that read like instructions to an AI.",
            )
    if activity.last_done_at is None:
        add("no_activity_logged", "Nothing has been logged as done on this deal.")
    else:
        quiet = max((now - activity.last_done_at).days, 0)
        if quiet >= QUIET_AFTER_DAYS:
            add("no_recent_activity", f"Nothing was done on the deal for {quiet} days.")
    if activity.overdue_tasks:
        add("overdue_tasks", f"{activity.overdue_tasks} task(s) on the deal are overdue.")
    elif activity.open_tasks:
        add("open_tasks", f"{activity.open_tasks} open task(s) on the deal.")
    if deal.primary_contact_id is None:
        add("no_primary_contact", "The deal has no primary contact.")
    return FactSheet("momentum", tuple(facts))
