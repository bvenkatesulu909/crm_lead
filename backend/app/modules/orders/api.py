"""Public interface of the orders module.

``customer_orders`` and ``customer_order`` are what the AI assistant will use to answer "where is
my order?". They run AS the signed-in customer, so the portal rules apply: only orders of the
customer's granted accounts, never drafts, never internal notes, nothing in another tenant.

``order_for_invoicing`` gives the invoices module a read-only snapshot of an order (its frozen
lines and amounts). It applies the staff read policy: an order the caller cannot see is None.

``mark_invoiced`` / ``release_invoiced`` are the invoices module's way to tell orders "this
order has a live invoice now" / "not any more". While the mark is set the order cannot be
cancelled. They are plain function calls in the caller's transaction (no events), so the mark
and the invoice are committed or rolled back together.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.records import RecordFacts
from app.core.reporting import Cell, Column, ExportFilters, ExportSpec, export_rows
from app.modules.orders import repository
from app.modules.orders.metrics import (
    OrderMetrics,
    order_metrics,
    orders_by_month_table,
    recent_order_activities,
)
from app.modules.orders.models import ORDER_STATUSES, Order
from app.modules.orders.policies import readable_orders
from app.modules.orders.service import customer_order, customer_orders

__all__ = [
    "orders_by_month_table",
    "EXPORT",
    "export_table",
    "order_facts",
    "ORDER_STATUSES",
    "NewOrderLine",
    "create_order_from_quote",
    "last_order_by_account",
    "OrderLineSnapshot",
    "OrderMetrics",
    "OrderSnapshot",
    "customer_order",
    "customer_orders",
    "mark_invoiced",
    "order_for_invoicing",
    "order_metrics",
    "recent_order_activities",
    "release_invoiced",
]


@dataclass(frozen=True)
class OrderLineSnapshot:
    position: int
    product_code: str | None
    description: str
    quantity: Decimal
    unit_price: Decimal
    tax_rate: Decimal
    line_subtotal: Decimal
    line_tax: Decimal
    line_total: Decimal


@dataclass(frozen=True)
class OrderSnapshot:
    id: uuid.UUID
    number: int
    account_id: uuid.UUID
    status: str
    currency: str
    customer_reference: str | None
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    lines: tuple[OrderLineSnapshot, ...]


def order_for_invoicing(
    session: Session, principal: Principal, order_id: uuid.UUID
) -> OrderSnapshot | None:
    order = repository.get_readable(session, principal, order_id)
    if order is None:
        return None
    return OrderSnapshot(
        id=order.id,
        number=order.number,
        account_id=order.account_id,
        status=order.status,
        currency=order.currency,
        customer_reference=order.customer_reference,
        subtotal=order.subtotal,
        tax_total=order.tax_total,
        total=order.total,
        lines=tuple(
            OrderLineSnapshot(
                position=line.position,
                product_code=line.product_code,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                tax_rate=line.tax_rate,
                line_subtotal=line.line_subtotal,
                line_tax=line.line_tax,
                line_total=line.line_total,
            )
            for line in repository.lines(session, order)
        ),
    )


def mark_invoiced(
    session: Session, principal: Principal, order_id: uuid.UUID, *, statuses: frozenset[str]
) -> bool:
    """Marks the order as having a live invoice, if it is (still) in one of ``statuses``.

    The UPDATE takes the row lock that ``change_status`` also takes, so "invoice it" and
    "cancel it" cannot both succeed: whichever comes second sees the other's result. False
    means the order is not visible to the caller or no longer in an invoiceable status.

    The ``version`` is deliberately not increased: this is not an edit of the order, and an
    open order page must keep working."""
    marked = session.execute(
        update(Order)
        .where(
            Order.tenant_id == principal.tenant_id,
            Order.id == order_id,
            Order.status.in_(statuses),
            readable_orders(principal),
        )
        .values(invoiced_at=func.clock_timestamp())
        .returning(Order.id)
    ).first()
    return marked is not None


def release_invoiced(session: Session, tenant_id: uuid.UUID, order_id: uuid.UUID) -> None:
    """Removes the mark again (the order's only live invoice was discarded)."""
    session.execute(
        update(Order)
        .where(Order.tenant_id == tenant_id, Order.id == order_id)
        .values(invoiced_at=None)
    )


def last_order_by_account(
    session: Session, tenant_id: uuid.UUID, account_ids: list[uuid.UUID]
) -> dict[uuid.UUID, datetime]:
    """When each account last placed (or had created) an order. Drafts count as contact."""
    if not account_ids:
        return {}
    rows = session.execute(
        select(Order.account_id, func.max(Order.created_at))
        .where(Order.tenant_id == tenant_id, Order.account_id.in_(account_ids))
        .group_by(Order.account_id)
    ).all()
    return {account: at for account, at in rows}


@dataclass(frozen=True)
class NewOrderLine:
    product_code: str | None
    description: str
    quantity: Decimal
    unit_price: Decimal
    tax_rate: Decimal


def create_order_from_quote(
    session: Session,
    principal: Principal,
    *,
    account_id: uuid.UUID,
    currency: str,
    customer_reference: str | None,
    internal_note: str | None,
    lines: list[NewOrderLine],
) -> tuple[uuid.UUID, int]:
    """Create a DRAFT order from an accepted quote, AS the user (the normal order rules apply:
    order permissions and, for agents, only their own accounts). Returns (id, number)."""
    from app.modules.orders.schemas import OrderLineInput
    from app.modules.orders.service import create_order

    order = create_order(
        session,
        principal,
        account_id=account_id,
        currency=currency,
        customer_reference=customer_reference,
        expected_delivery_date=None,
        internal_note=internal_note,
        lines=[
            OrderLineInput(
                product_code=line.product_code,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                tax_rate=line.tax_rate,
            )
            for line in lines
        ],
    )
    return order.id, order.number


def order_facts(session: Session, principal: Principal, order_id: uuid.UUID) -> RecordFacts | None:
    order = repository.get_readable(session, principal, order_id)
    if order is None:
        return None
    return RecordFacts(
        record_type="order",
        record_id=order.id,
        label=f"SO-{order.number:04d}",
        link=f"/orders/{order.id}",
        owner_id=None,  # the account's owner is responsible (looked up by the caller)
        account_id=order.account_id,
        lead_id=None,
        values={"status": order.status, "total": order.total, "currency": order.currency},
    )


# Report builder (Phase 18): the columns that may be exported - never internal notes - and the
# statuses to filter by. Rows always pass through this module's own record-level policy.
EXPORT = ExportSpec(
    columns=(
        Column("created_at", "Created", "datetime"),
        Column("number", "Order no.", "number"),
        Column("account_id", "Account", "account"),
        Column("status", "Status", "text"),
        Column("total", "Total", "money"),
        Column("currency", "Currency", "text"),
        Column("confirmed_at", "Confirmed", "datetime"),
        Column("delivered_at", "Delivered", "datetime"),
    ),
    statuses=ORDER_STATUSES,
)


def export_table(
    session: Session, principal: Principal, filters: ExportFilters, wanted: list[str]
) -> list[dict[str, Cell]]:
    allowed = {c.key for c in EXPORT.columns}
    if not wanted or not set(wanted) <= allowed:
        raise ValueError("unknown export column")
    return export_rows(
        session,
        entity=Order,
        columns={key: getattr(Order, key) for key in allowed},
        wanted=wanted,
        condition=readable_orders(principal),
        created=Order.created_at,
        owner=None,
        status=Order.status,
        filters=filters,
    )
