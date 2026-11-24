"""Gathering the signals for one deal (ADR 0037, DR2).

Everything is read through the other modules' ``api.py`` AS THE PERSON ASKING (the nightly job
asks as the organisation's Automation identity). A deal they may not read - or a closed one - is
"not found"; a signal they may not read is left as None, which the rules list as unknown and never
count as good news.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.errors import DomainError, NotFoundError
from app.modules.activities import api as activities_api
from app.modules.deal_risk import baseline
from app.modules.deal_risk.rules import Signals
from app.modules.quotes import api as quotes_api
from app.modules.relationships import api as relationships_api
from app.modules.sales import api as sales_api


class DealNotFoundError(NotFoundError):
    code = "deal_not_found"

    def __init__(self) -> None:
        super().__init__("Deal not found.")


def quote_state(quotes: list[quotes_api.DealQuote], today: datetime) -> str:
    """The state of the newest live quote: none | expired | declined | approval_waiting | ok."""
    live = [q for q in quotes if q.status != "superseded" and q.status != "draft"]
    if not live:
        return "none"
    newest = live[0]  # deal_quotes returns the newest first
    if newest.status == "declined":
        return "declined"
    if newest.status == "pending_approval":
        return "approval_waiting"
    if newest.status != "accepted" and newest.valid_until < today.date():
        return "expired"
    return "ok"


def gather(
    session: Session,
    principal: Principal,
    opp_id: uuid.UUID,
    now: datetime,
    history: sales_api.WonHistory,
) -> Signals:
    deal = sales_api.risk_inputs(session, principal, opp_id)
    if deal is None:
        raise DealNotFoundError

    done = activities_api.deal_activity(session, principal, deal.id, now)
    touched = max(t for t in (done.last_done_at, deal.created_at) if t is not None)

    quotes = quotes_api.deal_quotes(session, principal, deal.id)

    try:
        health: str | None = relationships_api.account_health(
            session, principal, deal.account_id
        ).label
    except DomainError:  # the account is not visible to this person
        health = None

    typical_amount: Decimal | None = baseline.typical_amount(history.amounts.get(deal.currency))

    return Signals(
        stage=deal.stage,
        now=now,
        days_since_last_activity=max((now - touched).days, 0),
        overdue_tasks=done.overdue_tasks,
        open_tasks=done.open_tasks,
        has_next_step=deal.has_next_step,
        expected_close_date=deal.expected_close_date,
        days_in_stage=max((now - deal.stage_entered_at).days, 0),
        typical_days_in_stage=baseline.typical_days(history.days_in_stage.get(deal.stage)),
        stage_went_back=deal.stage_went_back,
        quote_state=quote_state(quotes, now),
        account_health=health,
        has_primary_contact=deal.has_primary_contact,
        amount=deal.amount,
        typical_amount=typical_amount,
        # Not read in v1: close-date history, the number of contacts per deal, overdue invoices
        # and tickets of the account beyond what account health already says, call notes.
    )
