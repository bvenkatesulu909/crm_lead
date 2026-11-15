"""Gathering the deal desk's facts (ADR 0024, step DD1).

Everything is read through the other modules' ``api.py`` AS THE PERSON ASKING: a deal they may
not read is "not found" (the same answer as a deal that does not exist), quotes and activities
they may not read are left out, and an account they may not read gives no health facts.
"""

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.errors import DomainError, NotFoundError
from app.modules.activities import api as activities_api
from app.modules.contracts import api as contracts_api
from app.modules.deal_desk import rules
from app.modules.quotes import api as quotes_api
from app.modules.relationships import api as relationships_api
from app.modules.sales import api as sales_api


class DealNotFoundError(NotFoundError):
    code = "deal_not_found"

    def __init__(self) -> None:
        super().__init__("Deal not found.")


def build_sheets(
    session: Session, principal: Principal, opp_id: uuid.UUID, now: datetime
) -> rules.DealSheets:
    deal = sales_api.deal_facts(session, principal, opp_id)
    if deal is None:
        raise DealNotFoundError
    deal_in = rules.DealInput(
        id=deal.id,
        account_id=deal.account_id,
        stage=deal.stage,
        amount=deal.amount,
        currency=deal.currency,
        expected_close_date=deal.expected_close_date,
        next_step=deal.next_step,
        stage_entered_at=deal.stage_entered_at,
        primary_contact_id=deal.primary_contact_id,
        other_open_deals=deal.other_open_deals,
    )
    quotes = [
        rules.QuoteInput(
            id=q.id,
            label=q.label,
            status=q.status,
            currency=q.currency,
            total=q.total,
            max_discount_percent=q.max_discount_percent,
            approval_limit_percent=q.approval_limit_percent,
            valid_until=q.valid_until,
        )
        for q in quotes_api.deal_quotes(session, principal, deal.id)
    ]
    health: rules.HealthInput | None
    renewal: rules.RenewalInput | None = None
    try:
        found = relationships_api.account_health(session, principal, deal.account_id)
    except DomainError:  # the account is not visible to this person
        health = None
    else:
        health = rules.HealthInput(
            found.score, found.label, tuple(factor.label for factor in found.factors)
        )
        next_renewal = contracts_api.next_renewal(session, principal, deal.account_id)
        if next_renewal is not None:
            renewal = rules.RenewalInput(*next_renewal)
    done = activities_api.deal_activity(session, principal, deal.id, now)
    activity = rules.ActivityInput(done.last_done_at, done.open_tasks, done.overdue_tasks)
    return rules.DealSheets(
        opportunity_id=deal.id,
        pricing=rules.pricing_sheet(deal_in, quotes, now.date()),
        account=rules.account_sheet(deal_in, health, renewal, now.date()),
        momentum=rules.momentum_sheet(deal_in, activity, now),
    )
