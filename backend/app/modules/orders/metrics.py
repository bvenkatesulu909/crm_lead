"""Order figures and activity for dashboards. Applies ``readable_orders``."""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import ColumnElement, and_, func, select
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.reporting import ActivityItem, Column, Filters, Money, Table, money_by_currency
from app.modules.accounts import api as accounts_api
from app.modules.orders.models import Order, OrderStatusEvent
from app.modules.orders.policies import readable_orders

IN_PROGRESS = ("confirmed", "in_fulfilment", "shipped")


@dataclass(frozen=True)
class OrderMetrics:
    confirmed_in_period: int
    confirmed_value: list[Money]
    in_progress_now: int  # confirmed, being prepared or on the way


def _scope(principal: Principal, filters: Filters) -> ColumnElement[bool]:
    condition = readable_orders(principal)
    if filters.owner_id is not None and principal.tenant_id is not None:
        condition = and_(
            condition,
            Order.account_id.in_(
                accounts_api.accounts_owned_by(principal.tenant_id, filters.owner_id)
            ),
        )
    return condition


def order_metrics(session: Session, principal: Principal, filters: Filters) -> OrderMetrics:
    scope = _scope(principal, filters)
    period = filters.period
    confirmed = session.execute(
        select(Order.currency, func.count(), func.sum(Order.total))
        .where(scope, Order.confirmed_at >= period.start, Order.confirmed_at < period.end)
        .group_by(Order.currency)
    ).all()
    in_progress = session.scalar(select(func.count()).where(scope, Order.status.in_(IN_PROGRESS)))
    return OrderMetrics(
        confirmed_in_period=sum(n for _, n, _ in confirmed),
        confirmed_value=money_by_currency((c, v) for c, _, v in confirmed),
        in_progress_now=in_progress or 0,
    )


_EVENT_TITLES = {
    "confirmed": "Order confirmed",
    "shipped": "Order shipped",
    "delivered": "Order delivered",
    "cancelled": "Order cancelled",
}


def recent_order_activities(
    session: Session, principal: Principal, filters: Filters, *, limit: int = 15
) -> list[ActivityItem]:
    period = filters.period
    rows = session.execute(
        select(OrderStatusEvent, Order)
        .join(
            Order,
            and_(
                Order.tenant_id == OrderStatusEvent.tenant_id, Order.id == OrderStatusEvent.order_id
            ),
        )
        .where(
            _scope(principal, filters),
            OrderStatusEvent.to_status.in_(tuple(_EVENT_TITLES)),
            OrderStatusEvent.created_at >= period.start,
            OrderStatusEvent.created_at < period.end,
        )
        .order_by(OrderStatusEvent.created_at.desc(), OrderStatusEvent.seq.desc())
        .limit(limit)
    ).all()
    return [
        ActivityItem(
            at=event.created_at,
            kind=f"order.{event.to_status}",
            title=f"{_EVENT_TITLES[event.to_status]}: SO-{order.number:04d}",
            detail=f"{order.total} {order.currency}",
            record_type="order",
            record_id=order.id,
            actor_user_id=event.actor_user_id,
        )
        for event, order in rows
    ]


def orders_by_month_table(session: Session, principal: Principal, filters: Filters) -> Table:
    """Orders confirmed in the period per month and currency (cancelled ones counted apart)."""
    period = filters.period
    month = func.date_trunc("month", Order.confirmed_at)
    rows = session.execute(
        select(
            month,
            Order.currency,
            func.count().filter(Order.status != "cancelled"),
            func.sum(Order.total).filter(Order.status != "cancelled"),
            func.count().filter(Order.status == "cancelled"),
        )
        .where(
            _scope(principal, filters),
            Order.confirmed_at >= period.start,
            Order.confirmed_at < period.end,
        )
        .group_by(month, Order.currency)
        .order_by(month, Order.currency)
    ).all()
    return Table(
        "Orders by month",
        (
            Column("month", "Month"),
            Column("orders", "Orders", "number"),
            Column("value", "Order value", "money"),
            Column("cancelled", "Cancelled", "number"),
            Column("currency", "Currency"),
        ),
        [
            {
                "month": when.strftime("%Y-%m"),
                "currency": currency,
                "orders": count,
                "value": value or Decimal("0.00"),
                "cancelled": cancelled,
            }
            for when, currency, count, value, cancelled in rows
        ],
    )
