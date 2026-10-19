"""Order business rules. Functions never commit; routers commit once per request.

Every important change writes an audit_log row in the same transaction.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import cast

from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.core.events import publish as publish_event
from app.modules.accounts import api as accounts_api
from app.modules.identity import api as identity_api
from app.modules.orders import repository
from app.modules.orders.models import Order, OrderLine, OrderStatusEvent
from app.modules.orders.policies import can_fulfil, can_write_any
from app.modules.orders.repository import OrderFilters
from app.modules.orders.rules import (
    FULFILMENT_STARTED,
    FULFILMENT_TARGETS,
    check_transition,
    line_amounts,
    order_totals,
)
from app.modules.orders.schemas import (
    OrderEventRead,
    OrderLineInput,
    OrderLineRead,
    OrderRead,
    OrderStatus,
    PortalOrderRead,
    PortalOrderStep,
    PortalOrderSummary,
)

ENTITY = "order"


class OrderNotFoundError(NotFoundError):
    code = "order_not_found"

    def __init__(self) -> None:
        super().__init__("Order not found.")


class OrderNotEditableError(ConflictError):
    code = "order_not_editable"


class OrderHasNoLinesError(ConflictError):
    code = "order_has_no_lines"


class OrderInvoicedError(ConflictError):
    code = "order_invoiced"


class VersionConflictError(ConflictError):
    code = "version_conflict"


def _now() -> datetime:
    return datetime.now(UTC)


def _tenant(principal: Principal) -> uuid.UUID:
    if principal.tenant_id is None:
        raise ForbiddenError("Only members of an organisation can use orders.")
    return principal.tenant_id


def _flush(session: Session) -> None:
    try:
        session.flush()
    except StaleDataError as exc:
        raise VersionConflictError("The order was changed by someone else. Reload it.") from exc


def _audit(
    session: Session, principal: Principal, order: Order, action: str, changes: dict[str, object]
) -> None:
    record_audit(
        session, principal, action=action, entity_type=ENTITY, entity_id=order.id, changes=changes
    )


def _check_version(order: Order, version: int) -> None:
    if order.version != version:
        raise VersionConflictError(
            f"The order was changed by someone else (now version {order.version}). Reload it."
        )


def _event(
    session: Session,
    principal: Principal,
    order: Order,
    previous: str | None,
    target: str,
    note: str | None,
) -> None:
    session.add(
        OrderStatusEvent(
            tenant_id=order.tenant_id,
            order_id=order.id,
            from_status=previous,
            to_status=target,
            actor_user_id=principal.user_id,
            note=note,
        )
    )


def _replace_lines(session: Session, order: Order, items: Sequence[OrderLineInput]) -> None:
    """Writes the lines with server-calculated amounts and updates the order totals.

    The order's own changes are made FIRST: the DELETE below flushes them in one UPDATE, so
    the version number goes up exactly once per request."""
    amounts = [line_amounts(i.quantity, i.unit_price, i.tax_rate) for i in items]
    totals = order_totals(amounts)
    order.subtotal, order.tax_total, order.total = totals.subtotal, totals.tax_total, totals.total
    repository.delete_lines(session, order)
    for position, (item, line) in enumerate(zip(items, amounts, strict=True), start=1):
        session.add(
            OrderLine(
                tenant_id=order.tenant_id,
                order_id=order.id,
                position=position,
                product_code=item.product_code,
                description=item.description,
                quantity=item.quantity,
                unit_price=item.unit_price,
                tax_rate=item.tax_rate,
                line_subtotal=line.subtotal,
                line_tax=line.tax,
                line_total=line.total,
            )
        )


# --- views --------------------------------------------------------------------------------


def _lines_view(session: Session, order: Order) -> list[OrderLineRead]:
    return [OrderLineRead.model_validate(line) for line in repository.lines(session, order)]


def to_staff_view(session: Session, order: Order) -> OrderRead:
    events = repository.events(session, order)
    people = identity_api.people_by_id(
        session, order.tenant_id, {e.actor_user_id for e in events if e.actor_user_id}
    )
    columns = {c.key: getattr(order, c.key) for c in Order.__table__.columns}
    return OrderRead.model_validate(
        {
            **columns,
            "lines": _lines_view(session, order),
            "events": [
                OrderEventRead(
                    from_status=cast(OrderStatus | None, e.from_status),
                    to_status=cast(OrderStatus, e.to_status),
                    actor_name=people.get(e.actor_user_id, ("Former user", ""))[0]
                    if e.actor_user_id
                    else "System",
                    note=e.note,
                    created_at=e.created_at,
                )
                for e in events
            ],
        }
    )


def to_portal_summary(order: Order) -> PortalOrderSummary:
    return PortalOrderSummary.model_validate(order)


def to_portal_view(session: Session, order: Order) -> PortalOrderRead:
    # The customer's timeline starts at confirmation: drafts are internal.
    timeline = [
        PortalOrderStep(status=cast(OrderStatus, e.to_status), at=e.created_at)
        for e in repository.events(session, order)
        if e.to_status != "draft"
    ]
    return PortalOrderRead.model_validate(
        {
            **PortalOrderSummary.model_validate(order).model_dump(),
            "subtotal": order.subtotal,
            "tax_total": order.tax_total,
            "tracking_reference": order.tracking_reference,
            "shipped_at": order.shipped_at,
            "delivered_at": order.delivered_at,
            "cancelled_at": order.cancelled_at,
            "cancellation_reason": order.cancellation_reason,
            "lines": _lines_view(session, order),
            "timeline": timeline,
        }
    )


# --- read ---------------------------------------------------------------------------------


def get_order(session: Session, principal: Principal, order_id: uuid.UUID) -> Order:
    order = repository.get_readable(session, principal, order_id)
    if order is None:
        raise OrderNotFoundError()
    return order


def list_orders(
    session: Session, principal: Principal, filters: OrderFilters
) -> tuple[Sequence[Order], int]:
    return repository.search(session, principal, filters)


# --- create and edit (staff) --------------------------------------------------------------


def _may_order_for(session: Session, principal: Principal, account_id: uuid.UUID) -> bool:
    if principal.has_permission(Permission.ORDER_WRITE_ALL):
        return accounts_api.is_readable_account(session, principal, account_id)
    return accounts_api.is_owned_account(session, principal, account_id)


def create_order(
    session: Session,
    principal: Principal,
    *,
    account_id: uuid.UUID,
    currency: str,
    customer_reference: str | None,
    expected_delivery_date: date | None,
    internal_note: str | None,
    lines: Sequence[OrderLineInput],
) -> Order:
    tenant_id = _tenant(principal)
    if not can_write_any(principal):
        raise ForbiddenError("You may not create orders.")
    # Agents may only order for accounts they own; anything else looks like a missing account.
    if not _may_order_for(session, principal, account_id):
        raise NotFoundError("Account not found.")
    now = _now()
    order = Order(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        number=repository.next_order_number(session, tenant_id),
        account_id=account_id,
        created_by_user_id=principal.user_id,
        status="draft",
        currency=currency,
        customer_reference=customer_reference,
        expected_delivery_date=expected_delivery_date,
        internal_note=internal_note,
        created_at=now,
        updated_at=now,
    )
    session.add(order)
    _replace_lines(session, order, lines)
    _event(session, principal, order, None, "draft", None)
    _audit(
        session,
        principal,
        order,
        "order.created",
        {"number": order.number, "account_id": account_id, "lines": len(lines)},
    )
    _flush(session)
    return order


def _load_for_change(session: Session, principal: Principal, order_id: uuid.UUID) -> Order:
    order = repository.get_writable_for_update(session, principal, order_id)
    if order is None:
        if repository.get_readable(session, principal, order_id) is not None:
            raise ForbiddenError("You may view this order but not change it.")
        raise OrderNotFoundError()
    return order


def update_draft(
    session: Session,
    principal: Principal,
    order_id: uuid.UUID,
    *,
    version: int,
    currency: str,
    customer_reference: str | None,
    expected_delivery_date: date | None,
    internal_note: str | None,
    lines: Sequence[OrderLineInput],
) -> Order:
    order = _load_for_change(session, principal, order_id)
    if order.status != "draft":
        raise OrderNotEditableError("Only draft orders can be edited.")
    _check_version(order, version)
    previous_total = order.total
    order.currency = currency
    order.customer_reference = customer_reference
    order.expected_delivery_date = expected_delivery_date
    order.internal_note = internal_note
    order.updated_at = _now()
    _replace_lines(session, order, lines)
    _audit(
        session,
        principal,
        order,
        "order.updated",
        {"total": {"old": previous_total, "new": order.total}, "lines": len(lines)},
    )
    _flush(session)
    return order


def change_status(
    session: Session,
    principal: Principal,
    order_id: uuid.UUID,
    *,
    target: str,
    version: int,
    reason: str | None = None,
    note: str | None = None,
    tracking_reference: str | None = None,
    expected_delivery_date: date | None = None,
) -> Order:
    order = _load_for_change(session, principal, order_id)
    previous = order.status
    check_transition(previous, target)
    if target in FULFILMENT_TARGETS and not can_fulfil(principal):
        raise ForbiddenError("Only fulfilment staff can move an order through delivery.")
    if target == "cancelled" and previous in FULFILMENT_STARTED and not can_fulfil(principal):
        raise ForbiddenError("This order is already being prepared. Ask fulfilment to cancel it.")
    _check_version(order, version)
    if target == "cancelled" and order.invoiced_at is not None:
        # A draft invoice must be discarded first. An issued invoice is final: the order stays
        # as it is and the money side is corrected with a credit note.
        raise OrderInvoicedError(
            "This order has an invoice. Discard a draft invoice first; "
            "an issued invoice is corrected with a credit note instead."
        )
    if target == "confirmed" and not repository.lines(session, order):
        raise OrderHasNoLinesError("Add at least one line before confirming the order.")

    now = _now()
    order.status = target
    if target == "confirmed":
        order.confirmed_at = now
    elif target == "shipped":
        order.shipped_at = now
        order.tracking_reference = tracking_reference
    elif target == "delivered":
        order.delivered_at = now
    elif target == "cancelled":
        order.cancelled_at = now
        order.cancellation_reason = reason
    if expected_delivery_date is not None:
        order.expected_delivery_date = expected_delivery_date
    order.updated_at = now
    _event(session, principal, order, previous, target, note)
    _audit(
        session,
        principal,
        order,
        "order.status_changed",
        {"status": {"old": previous, "new": target}, "reason": reason},
    )
    publish_event(
        session,
        order.tenant_id,
        "order.status_changed",
        {
            "order_id": str(order.id),
            "status": target,
            "previous": previous,
            "actor_id": str(principal.user_id) if principal.user_id else None,
        },
    )
    _flush(session)
    return order


# --- customer (portal and AI assistant) ---------------------------------------------------


def _require_customer(principal: Principal) -> None:
    if principal.user_type != "customer" or not principal.has_permission(
        Permission.PORTAL_ORDER_READ
    ):
        raise ForbiddenError("Only customers can use the portal order view.")


def customer_orders(
    session: Session,
    principal: Principal,
    *,
    account_id: uuid.UUID | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[PortalOrderSummary]:
    _require_customer(principal)
    filters = OrderFilters(q=q, account_id=account_id, limit=limit, offset=offset)
    items, _ = repository.search(session, principal, filters)
    return [to_portal_summary(o) for o in items]


def customer_order(session: Session, principal: Principal, order_id: uuid.UUID) -> PortalOrderRead:
    _require_customer(principal)
    return to_portal_view(session, get_order(session, principal, order_id))
