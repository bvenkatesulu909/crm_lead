"""Database queries for orders. Every query applies ``readable_orders`` (or ``writable_orders``)."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import ColumnElement, Select, delete, func, or_, select, text
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.search import escape_like
from app.modules.orders.models import Order, OrderLine, OrderStatusEvent
from app.modules.orders.policies import readable_orders, writable_orders

_SORTS = {"created_at": Order.created_at, "updated_at": Order.updated_at, "total": Order.total}


@dataclass(frozen=True)
class OrderFilters:
    q: str | None = None
    statuses: tuple[str, ...] = ()
    account_id: uuid.UUID | None = None
    sort: str = "-created_at"
    limit: int = 50
    offset: int = 0


def next_order_number(session: Session, tenant_id: uuid.UUID) -> int:
    """Atomically take the next number for this tenant (safe under concurrent requests)."""
    number = session.scalar(
        text(
            "INSERT INTO order_number_counters (tenant_id, last_number) VALUES (:t, 1) "
            "ON CONFLICT (tenant_id) DO UPDATE "
            "SET last_number = order_number_counters.last_number + 1 "
            "RETURNING last_number"
        ),
        {"t": tenant_id},
    )
    if number is None:
        raise RuntimeError("could not allocate an order number")
    return int(number)


def _filtered(principal: Principal, filters: OrderFilters) -> Select[Order]:
    statement = select(Order).where(readable_orders(principal))
    if filters.q:
        term = filters.q.strip()
        digits = term.upper().removeprefix("SO-").lstrip("0")
        conditions: list[ColumnElement[bool]] = [
            Order.customer_reference.ilike(f"%{escape_like(term)}%", escape="\\")
        ]
        if digits.isdigit() and len(digits) < 10:
            conditions.append(Order.number == int(digits))
        statement = statement.where(or_(*conditions))
    if filters.statuses:
        statement = statement.where(Order.status.in_(filters.statuses))
    if filters.account_id:
        statement = statement.where(Order.account_id == filters.account_id)
    return statement


def search(
    session: Session, principal: Principal, filters: OrderFilters
) -> tuple[Sequence[Order], int]:
    statement = _filtered(principal, filters)
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    column = _SORTS[filters.sort.lstrip("-")]
    order = column.desc() if filters.sort.startswith("-") else column.asc()
    page = statement.order_by(order, Order.id).limit(filters.limit).offset(filters.offset)
    return session.scalars(page).all(), total


def get_readable(session: Session, principal: Principal, order_id: uuid.UUID) -> Order | None:
    statement = select(Order).where(Order.id == order_id, readable_orders(principal))
    return session.scalars(statement).one_or_none()


def get_writable_for_update(
    session: Session, principal: Principal, order_id: uuid.UUID
) -> Order | None:
    """Locks the row so two requests cannot change the same order at the same time."""
    statement = (
        select(Order)
        .where(Order.id == order_id, readable_orders(principal), writable_orders(principal))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return session.scalars(statement).one_or_none()


def lines(session: Session, order: Order) -> Sequence[OrderLine]:
    return session.scalars(
        select(OrderLine)
        .where(OrderLine.tenant_id == order.tenant_id, OrderLine.order_id == order.id)
        .order_by(OrderLine.position)
    ).all()


def delete_lines(session: Session, order: Order) -> None:
    session.execute(
        delete(OrderLine).where(
            OrderLine.tenant_id == order.tenant_id, OrderLine.order_id == order.id
        )
    )


def events(session: Session, order: Order) -> Sequence[OrderStatusEvent]:
    return session.scalars(
        select(OrderStatusEvent)
        .where(OrderStatusEvent.tenant_id == order.tenant_id, OrderStatusEvent.order_id == order.id)
        .order_by(OrderStatusEvent.seq)
    ).all()
