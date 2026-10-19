"""Customer relationships: ownership transfer and customer health.

This module owns no tables. It coordinates the other modules through their public api.py,
in ONE transaction (the router commits once): a transfer either moves the account and the
chosen related records together, or nothing at all.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.modules.accounts import api as accounts_api
from app.modules.activities import api as activities_api
from app.modules.contacts import api as contacts_api
from app.modules.invoices import api as invoices_api
from app.modules.orders import api as orders_api
from app.modules.relationships.health import Signals, assess
from app.modules.relationships.schemas import (
    FactorRead,
    HealthOverview,
    HealthRead,
    HealthRow,
    MoneyRead,
    Transfer,
    TransferResult,
)
from app.modules.sales import api as sales_api
from app.modules.support import api as support_api

MAX_ASSESSED = 500


def transfer(
    session: Session, principal: Principal, account_id: uuid.UUID, data: Transfer
) -> TransferResult:
    account, previous = accounts_api.transfer_owner(
        session,
        principal,
        account_id,
        version=data.version,
        new_owner_id=data.new_owner_id,
        reason=data.reason,
    )
    tenant_id = account.tenant_id
    contact_ids = contacts_api.contact_ids_by_account(session, tenant_id, [account.id])[account.id]
    deal_ids = sales_api.opportunity_ids_by_account(session, tenant_id, [account.id])[account.id]
    moved_contacts = (
        contacts_api.transfer_account_contacts(
            session, principal, account.id, previous, data.new_owner_id
        )
        if data.include_contacts
        else []
    )
    moved_deals = (
        sales_api.transfer_open_opportunities(
            session, principal, account.id, previous, data.new_owner_id
        )
        if data.include_open_opportunities
        else []
    )
    moved_tasks = (
        activities_api.reassign_open_activities(
            session,
            principal,
            account_id=account.id,
            contact_ids=contact_ids,
            opportunity_ids=deal_ids,
            from_user=previous,
            to_user=data.new_owner_id,
        )
        if data.include_open_tasks and previous is not None
        else []
    )
    accounts_api.record_account_event(
        session,
        principal,
        account.id,
        "account.owner_transferred",
        {
            "moved": {
                "contacts": len(moved_contacts),
                "opportunities": len(moved_deals),
                "tasks": len(moved_tasks),
            }
        },
    )
    return TransferResult(
        account_id=account.id,
        previous_owner_id=previous,
        new_owner_id=data.new_owner_id,
        version=account.version,
        contacts_moved=len(moved_contacts),
        opportunities_moved=len(moved_deals),
        tasks_moved=len(moved_tasks),
    )


def _signals(
    session: Session, tenant_id: uuid.UUID, accounts: list[tuple[uuid.UUID, str | None]]
) -> dict[uuid.UUID, Signals]:
    """All signals for many accounts with one batch query per module."""
    ids = [account_id for account_id, _ in accounts]
    contacts = contacts_api.contact_ids_by_account(session, tenant_id, ids)
    deals = sales_api.opportunity_ids_by_account(session, tenant_id, ids)
    activity = activities_api.last_interaction_by_account(
        session, tenant_id, {a: (contacts[a], deals[a]) for a in ids}
    )
    orders = orders_api.last_order_by_account(session, tenant_id, ids)
    tickets = support_api.ticket_signals_by_account(session, tenant_id, ids)
    overdue = invoices_api.overdue_invoices_by_account(session, tenant_id, ids)
    won = sales_api.won_deals_by_account(
        session, tenant_id, ids, datetime.now(UTC) - timedelta(days=365)
    )
    result: dict[uuid.UUID, Signals] = {}
    for account_id, lifecycle in accounts:
        support = tickets.get(account_id, support_api.TicketSignals())
        moments = [activity.get(account_id), orders.get(account_id), support.last_ticket_at]
        known = [m for m in moments if m is not None]
        result[account_id] = Signals(
            last_interaction_at=max(known) if known else None,
            overdue_invoices=overdue.get(account_id, 0),
            sla_overdue_tickets=support.sla_overdue,
            open_complaints=support.open_complaints,
            average_rating=support.average_rating,
            won_deals_last_year=won.get(account_id, 0),
            lifecycle_stage=lifecycle,
        )
    return result


def account_health(session: Session, principal: Principal, account_id: uuid.UUID) -> HealthRead:
    account = accounts_api.get_account(session, principal, account_id)  # 404 if not visible
    signals = _signals(session, account.tenant_id, [(account.id, account.lifecycle_stage)])
    health = assess(signals[account.id], datetime.now(UTC))
    return HealthRead(
        account_id=account.id,
        score=health.score,
        label=health.label,
        last_interaction_at=signals[account.id].last_interaction_at,
        days_inactive=health.days_inactive,
        inactive=health.inactive,
        factors=[FactorRead(label=f.label, impact=f.impact) for f in health.factors],
        lifetime_value=[
            MoneyRead(currency=c, amount=a)
            for c, a in invoices_api.lifetime_value(session, account.tenant_id, account.id)
        ],
    )


def overview(
    session: Session, principal: Principal, *, owner_id: uuid.UUID | None, limit: int
) -> HealthOverview:
    accounts = accounts_api.readable_summaries(
        session, principal, owner_id=owner_id, limit=min(limit, MAX_ASSESSED)
    )
    if not accounts or principal.tenant_id is None:
        return HealthOverview(assessed=0, at_risk=0, watch=0, healthy=0, inactive=0, items=[])
    signals = _signals(session, principal.tenant_id, [(a.id, a.lifecycle_stage) for a in accounts])
    now = datetime.now(UTC)
    rows: list[HealthRow] = []
    for account in accounts:
        health = assess(signals[account.id], now)
        worst = min(health.factors, key=lambda f: f.impact, default=None)
        rows.append(
            HealthRow(
                account_id=account.id,
                name=account.name,
                owner_id=account.owner_id,
                lifecycle_stage=account.lifecycle_stage,
                score=health.score,
                label=health.label,
                days_inactive=health.days_inactive,
                inactive=health.inactive,
                top_factor=worst.label if worst and worst.impact < 0 else None,
            )
        )
    rows.sort(key=lambda r: (r.score, r.name.lower()))
    return HealthOverview(
        assessed=len(rows),
        at_risk=sum(r.label == "at_risk" for r in rows),
        watch=sum(r.label == "watch" for r in rows),
        healthy=sum(r.label == "healthy" for r in rows),
        inactive=sum(r.inactive for r in rows),
        items=rows,
    )
