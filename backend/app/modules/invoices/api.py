"""Public interface of the invoices module.

``customer_invoices`` and ``customer_invoice`` are what the AI assistant will use to answer
"what do I still owe?" or "was my payment received?". They run AS the signed-in customer, so
the portal rules apply: only issued invoices of the customer's granted accounts, nothing in
another tenant, no staff-only details.
"""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.errors import ForbiddenError
from app.core.reporting import Cell, Column, ExportFilters, ExportSpec, export_rows
from app.modules.invoices import service
from app.modules.invoices.metrics import RevenueMetrics, revenue_by_month_table, revenue_metrics
from app.modules.invoices.models import INVOICE_STATUSES, Invoice
from app.modules.invoices.policies import readable_invoices
from app.modules.invoices.repository import InvoiceFilters
from app.modules.invoices.service import customer_invoice, customer_invoices

__all__ = [
    "revenue_by_month_table",
    "EXPORT",
    "export_table",
    "RevenueMetrics",
    "accounts_with_value",
    "customer_invoice",
    "customer_invoices",
    "lifetime_value",
    "overdue_invoices_by_account",
    "revenue_metrics",
]


def accounts_with_value(tenant_id: uuid.UUID, currency: str, minimum: Decimal) -> Select[uuid.UUID]:
    """Subquery: accounts whose ISSUED invoices in ``currency`` add up to at least ``minimum``
    (customer value for segmentation; currencies are never mixed)."""
    return (
        select(Invoice.account_id)
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.status == "issued",
            Invoice.currency == currency,
        )
        .group_by(Invoice.account_id)
        .having(func.sum(Invoice.total) >= minimum)
    )


def lifetime_value(
    session: Session, tenant_id: uuid.UUID, account_id: uuid.UUID
) -> list[tuple[str, Decimal]]:
    """(currency, total of issued invoices) for one account. The caller checks access."""
    rows = session.execute(
        select(Invoice.currency, func.sum(Invoice.total))
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.account_id == account_id,
            Invoice.status == "issued",
        )
        .group_by(Invoice.currency)
        .order_by(Invoice.currency)
    ).all()
    return [(currency, total) for currency, total in rows]


def overdue_invoices_by_account(
    session: Session, tenant_id: uuid.UUID, account_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Number of issued invoices past their due date with money still owed, per account."""
    if not account_ids:
        return {}
    rows = session.execute(
        select(Invoice.account_id, func.count())
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.account_id.in_(account_ids),
            Invoice.status == "issued",
            Invoice.balance_due > 0,
            Invoice.due_date < func.current_date(),
        )
        .group_by(Invoice.account_id)
    ).all()
    return {account: count for account, count in rows}


# Report builder (Phase 18): the columns that may be exported - never internal notes - and the
# statuses to filter by. Rows always pass through this module's own record-level policy.
EXPORT = ExportSpec(
    columns=(
        Column("created_at", "Created", "datetime"),
        Column("number", "Invoice no.", "number"),
        Column("account_id", "Account", "account"),
        Column("status", "Status", "text"),
        Column("total", "Total", "money"),
        Column("amount_paid", "Paid", "money"),
        Column("currency", "Currency", "text"),
        Column("issued_at", "Issued", "datetime"),
        Column("due_date", "Due", "date"),
    ),
    statuses=INVOICE_STATUSES,
)


def export_table(
    session: Session, principal: Principal, filters: ExportFilters, wanted: list[str]
) -> list[dict[str, Cell]]:
    allowed = {c.key for c in EXPORT.columns}
    if not wanted or not set(wanted) <= allowed:
        raise ValueError("unknown export column")
    return export_rows(
        session,
        entity=Invoice,
        columns={key: getattr(Invoice, key) for key in allowed},
        wanted=wanted,
        condition=readable_invoices(principal),
        created=Invoice.created_at,
        owner=None,
        status=Invoice.status,
        filters=filters,
    )


# --- staff assistant (read-only, record-policy enforced) -------------------------------------


def search_invoices(
    session: Session, principal: Principal, *, limit: int = 10
) -> list[dict[str, Any]]:
    if not (
        principal.has_permission(Permission.INVOICE_READ_ALL)
        or principal.has_permission(Permission.INVOICE_READ_OWN_ACCOUNTS)
    ):
        raise ForbiddenError("You may not read invoices.")
    items, _ = service.list_invoices(session, principal, InvoiceFilters(limit=min(limit, 50)))
    return [
        {
            "id": str(x.id),
            "number": f"INV-{x.number:04d}" if x.number else None,
            "status": x.status,
            "total": str(x.total),
            "account_id": str(x.account_id),
            "link": f"/invoices/{x.id}",
        }
        for x in items
    ]
