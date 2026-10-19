"""Staff order endpoints (/api/v1/orders) and customer-portal order status endpoints
(/api/v1/portal/orders). Thin: permission gate, call the service, commit once."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.identity.api import require_any_permission
from app.modules.orders import service
from app.modules.orders.repository import OrderFilters
from app.modules.orders.schemas import (
    OrderCreate,
    OrderPage,
    OrderRead,
    OrderSort,
    OrderStatus,
    OrderStatusChange,
    OrderSummary,
    OrderUpdate,
    PortalOrderRead,
    PortalOrderSummary,
)

Db = Annotated[Session, Depends(get_db_session)]
OrderId = Annotated[uuid.UUID, "Order ID"]

# --- staff --------------------------------------------------------------------------------

router = APIRouter(prefix="/orders", tags=["orders"], responses=problem_responses(401, 403))
can_read = require_any_permission(Permission.ORDER_READ_ALL, Permission.ORDER_READ_OWN_ACCOUNTS)
can_write = require_any_permission(Permission.ORDER_WRITE_ALL, Permission.ORDER_WRITE_OWN_ACCOUNTS)
Reader = Annotated[Principal, Depends(can_read)]
Writer = Annotated[Principal, Depends(can_write)]


@router.get(
    "",
    summary="List and search orders",
    description="`q` matches the order number (e.g. `SO-12`) or the customer's reference. "
    "Only orders you may see are returned and counted.",
    responses=problem_responses(422),
)
def list_orders(
    principal: Reader,
    session: Db,
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    order_status: Annotated[list[OrderStatus] | None, Query(alias="status")] = None,
    account_id: uuid.UUID | None = None,
    sort: OrderSort = "-created_at",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> OrderPage:
    filters = OrderFilters(
        q=q.strip() if q else None,
        statuses=tuple(order_status or ()),
        account_id=account_id,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    items, total = service.list_orders(session, principal, filters)
    return OrderPage(
        items=[OrderSummary.model_validate(o) for o in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a draft order for a customer account",
    description="Line amounts and totals are calculated by the server.",
    responses=problem_responses(404, 422),
)
def create_order(
    data: OrderCreate, principal: Writer, session: Db, response: Response
) -> OrderRead:
    order = service.create_order(
        session,
        principal,
        account_id=data.account_id,
        currency=data.currency,
        customer_reference=data.customer_reference,
        expected_delivery_date=data.expected_delivery_date,
        internal_note=data.internal_note,
        lines=data.lines,
    )
    session.commit()
    response.headers["Location"] = f"/api/v1/orders/{order.id}"
    return service.to_staff_view(session, order)


@router.get(
    "/{order_id}",
    summary="Get one order with lines and history",
    responses=problem_responses(404),
)
def get_order(order_id: OrderId, principal: Reader, session: Db) -> OrderRead:
    return service.to_staff_view(session, service.get_order(session, principal, order_id))


@router.put(
    "/{order_id}",
    summary="Replace a draft order (header and all lines)",
    responses=problem_responses(404, 409, 422),
)
def update_order(order_id: OrderId, data: OrderUpdate, principal: Writer, session: Db) -> OrderRead:
    order = service.update_draft(
        session,
        principal,
        order_id,
        version=data.version,
        currency=data.currency,
        customer_reference=data.customer_reference,
        expected_delivery_date=data.expected_delivery_date,
        internal_note=data.internal_note,
        lines=data.lines,
    )
    session.commit()
    return service.to_staff_view(session, order)


@router.post(
    "/{order_id}/status",
    summary="Change the status",
    description="draft→confirmed|cancelled, confirmed→in_fulfilment|shipped|cancelled, "
    "in_fulfilment→shipped|cancelled, shipped→delivered. Delivered and cancelled are final. "
    "Fulfilment steps need `order:fulfil`; so does cancelling an order in fulfilment.",
    responses=problem_responses(404, 409, 422),
)
def change_status(
    order_id: OrderId, data: OrderStatusChange, principal: Writer, session: Db
) -> OrderRead:
    order = service.change_status(
        session,
        principal,
        order_id,
        target=data.status,
        version=data.version,
        reason=data.reason,
        note=data.note,
        tracking_reference=data.tracking_reference,
        expected_delivery_date=data.expected_delivery_date,
    )
    session.commit()
    return service.to_staff_view(session, order)


# --- customer portal ----------------------------------------------------------------------

portal_router = APIRouter(
    prefix="/portal/orders", tags=["portal"], responses=problem_responses(401, 403)
)
is_portal_reader = require_any_permission(Permission.PORTAL_ORDER_READ)
Customer = Annotated[Principal, Depends(is_portal_reader)]


@portal_router.get("", summary="My company's orders (drafts are never shown)")
def my_orders(
    principal: Customer,
    session: Db,
    account_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[PortalOrderSummary]:
    return service.customer_orders(
        session, principal, account_id=account_id, limit=limit, offset=offset
    )


@portal_router.get(
    "/{order_id}", summary="One of my orders with its status", responses=problem_responses(404)
)
def my_order(order_id: OrderId, principal: Customer, session: Db) -> PortalOrderRead:
    return service.customer_order(session, principal, order_id)
