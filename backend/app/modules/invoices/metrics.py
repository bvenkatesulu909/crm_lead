"""Revenue figures for the executive dashboard. Applies ``readable_invoices``.

Per currency, never converted. "Received" is payments minus reversals in the period.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, and_, case, func, select
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.reporting import Column, Filters, Money, Table, money_by_currency
from app.modules.accounts import api as accounts_api
from app.modules.invoices.models import Invoice, Payment
from app.modules.invoices.policies import readable_invoices


@dataclass(frozen=True)
class RevenueMetrics:
    issued_count: int  # invoices issued in the period
    issued_value: list[Money]
    received: list[Money]  # money received in the period (net of reversals)
    outstanding_count: int  # issued invoices with money still owed (now)
    outstanding: list[Money]
    overdue_count: int  # ... of which past their due date
    overdue: list[Money]


def _scope(principal: Principal, filters: Filters) -> ColumnElement[bool]:
    condition = and_(readable_invoices(principal), Invoice.status == "issued")
    if filters.owner_id is not None and principal.tenant_id is not None:
        condition = and_(
            condition,
            Invoice.account_id.in_(
                accounts_api.accounts_owned_by(principal.tenant_id, filters.owner_id)
            ),
        )
    return condition


def revenue_metrics(session: Session, principal: Principal, filters: Filters) -> RevenueMetrics:
    scope = _scope(principal, filters)
    period = filters.period
    issued = session.execute(
        select(Invoice.currency, func.count(), func.sum(Invoice.total))
        .where(
            scope, Invoice.issue_date >= period.start_date, Invoice.issue_date <= period.end_date
        )
        .group_by(Invoice.currency)
    ).all()
    signed = func.sum(
        case((Payment.reverses_payment_id.is_(None), Payment.amount), else_=-Payment.amount)
    )
    received = session.execute(
        select(Invoice.currency, signed)
        .join(
            Invoice, and_(Invoice.tenant_id == Payment.tenant_id, Invoice.id == Payment.invoice_id)
        )
        .where(
            scope, Payment.received_on >= period.start_date, Payment.received_on <= period.end_date
        )
        .group_by(Invoice.currency)
    ).all()
    owed = and_(scope, Invoice.balance_due > 0)
    outstanding = session.execute(
        select(Invoice.currency, func.count(), func.sum(Invoice.balance_due))
        .where(owed)
        .group_by(Invoice.currency)
    ).all()
    today = datetime.now(UTC).date()
    overdue = session.execute(
        select(Invoice.currency, func.count(), func.sum(Invoice.balance_due))
        .where(owed, Invoice.due_date < today)
        .group_by(Invoice.currency)
    ).all()
    return RevenueMetrics(
        issued_count=sum(n for _, n, _ in issued),
        issued_value=money_by_currency((c, v) for c, _, v in issued),
        received=money_by_currency((c, v) for c, v in received),
        outstanding_count=sum(n for _, n, _ in outstanding),
        outstanding=money_by_currency((c, v) for c, _, v in outstanding),
        overdue_count=sum(n for _, n, _ in overdue),
        overdue=money_by_currency((c, v) for c, _, v in overdue),
    )


def revenue_by_month_table(session: Session, principal: Principal, filters: Filters) -> Table:
    """Per month and currency: amount invoiced (issued) and payments received (net of
    reversals) in the period."""
    period = filters.period
    month = func.date_trunc("month", Invoice.issued_at)
    invoiced = session.execute(
        select(month, Invoice.currency, func.count(), func.sum(Invoice.total))
        .where(
            _scope(principal, filters),
            Invoice.issued_at >= period.start,
            Invoice.issued_at < period.end,
        )
        .group_by(month, Invoice.currency)
    ).all()
    pay_month = func.date_trunc("month", Payment.received_on)
    signed = case((Payment.reverses_payment_id.is_(None), Payment.amount), else_=-Payment.amount)
    paid = session.execute(
        select(pay_month, Invoice.currency, func.sum(signed))
        .join(
            Invoice, (Invoice.id == Payment.invoice_id) & (Invoice.tenant_id == Payment.tenant_id)
        )
        .where(
            _scope(principal, filters),
            Payment.received_on >= period.start_date,
            Payment.received_on <= period.end_date,
        )
        .group_by(pay_month, Invoice.currency)
    ).all()
    table: dict[tuple[str, str], dict[str, Any]] = {}
    for when, currency, count, total in invoiced:
        key = (when.strftime("%Y-%m"), currency)
        table[key] = {
            "month": key[0],
            "currency": currency,
            "invoices": count,
            "invoiced": total or Decimal("0.00"),
            "paid": Decimal("0.00"),
        }
    for when, currency, amount in paid:
        key = (when.strftime("%Y-%m"), currency)
        row = table.setdefault(
            key,
            {
                "month": key[0],
                "currency": currency,
                "invoices": 0,
                "invoiced": Decimal("0.00"),
                "paid": Decimal("0.00"),
            },
        )
        row["paid"] = amount or Decimal("0.00")
    return Table(
        "Revenue by month",
        (
            Column("month", "Month"),
            Column("invoices", "Invoices issued", "number"),
            Column("invoiced", "Invoiced", "money"),
            Column("paid", "Payments received", "money"),
            Column("currency", "Currency"),
        ),
        [table[k] for k in sorted(table)],
    )
