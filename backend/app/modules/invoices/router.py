"""Staff invoice endpoints (/api/v1/invoices) and customer-portal invoice endpoints
(/api/v1/portal/invoices). Thin: permission gate, call the service, commit once."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.identity.api import require_any_permission
from app.modules.invoices import service
from app.modules.invoices.repository import InvoiceFilters
from app.modules.invoices.schemas import (
    CreditNoteCreate,
    InvoiceDiscard,
    InvoiceFilter,
    InvoiceFromOrder,
    InvoiceIssue,
    InvoicePage,
    InvoiceRead,
    InvoiceSort,
    PaymentCreate,
    PaymentReversal,
    PortalInvoiceRead,
    PortalInvoiceSummary,
)

Db = Annotated[Session, Depends(get_db_session)]
InvoiceId = Annotated[uuid.UUID, "Invoice ID"]

# --- staff --------------------------------------------------------------------------------

router = APIRouter(prefix="/invoices", tags=["invoices"], responses=problem_responses(401, 403))
can_read = require_any_permission(Permission.INVOICE_READ_ALL, Permission.INVOICE_READ_OWN_ACCOUNTS)
Reader = Annotated[Principal, Depends(can_read)]
Manager = Annotated[Principal, Depends(require_any_permission(Permission.INVOICE_MANAGE))]
Cashier = Annotated[Principal, Depends(require_any_permission(Permission.PAYMENT_RECORD))]


@router.get(
    "",
    summary="List and search invoices",
    description="`q` matches the invoice number (e.g. `INV-12`) or the customer's reference. "
    "`state`: draft, unpaid (issued with money owed), overdue, paid, discarded.",
    responses=problem_responses(422),
)
def list_invoices(
    principal: Reader,
    session: Db,
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    state: InvoiceFilter | None = None,
    account_id: uuid.UUID | None = None,
    order_id: uuid.UUID | None = None,
    sort: InvoiceSort = "-created_at",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> InvoicePage:
    filters = InvoiceFilters(
        q=q.strip() if q else None,
        state=state,
        account_id=account_id,
        order_id=order_id,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    items, total = service.list_invoices(session, principal, filters)
    return InvoicePage(
        items=[service.to_summary(i) for i in items], total=total, limit=limit, offset=offset
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a draft invoice from an order",
    description="Lines, amounts, currency and customer account are copied from the order. "
    "One live invoice per order.",
    responses=problem_responses(404, 409, 422),
)
def create_invoice(
    data: InvoiceFromOrder, principal: Manager, session: Db, response: Response
) -> InvoiceRead:
    invoice = service.create_from_order(session, principal, data.order_id)
    session.commit()
    response.headers["Location"] = f"/api/v1/invoices/{invoice.id}"
    return service.to_staff_view(session, invoice)


@router.get(
    "/{invoice_id}",
    summary="Get one invoice with lines, credit notes and payments",
    responses=problem_responses(404),
)
def get_invoice(invoice_id: InvoiceId, principal: Reader, session: Db) -> InvoiceRead:
    return service.to_staff_view(session, service.get_invoice(session, principal, invoice_id))


@router.post(
    "/{invoice_id}/issue",
    summary="Issue a draft: gives it the next invoice number and freezes it",
    responses=problem_responses(404, 409, 422),
)
def issue_invoice(
    invoice_id: InvoiceId, data: InvoiceIssue, principal: Manager, session: Db
) -> InvoiceRead:
    invoice = service.issue(
        session, principal, invoice_id, version=data.version, due_date=data.due_date
    )
    session.commit()
    return service.to_staff_view(session, invoice)


@router.post(
    "/{invoice_id}/discard",
    summary="Discard a draft (it never gets a number)",
    responses=problem_responses(404, 409, 422),
)
def discard_invoice(
    invoice_id: InvoiceId, data: InvoiceDiscard, principal: Manager, session: Db
) -> InvoiceRead:
    invoice = service.discard(session, principal, invoice_id, version=data.version)
    session.commit()
    return service.to_staff_view(session, invoice)


@router.post(
    "/{invoice_id}/payments",
    status_code=status.HTTP_201_CREATED,
    summary="Record a received payment (at most the amount still owed)",
    responses=problem_responses(404, 409, 422),
)
def record_payment(
    invoice_id: InvoiceId, data: PaymentCreate, principal: Cashier, session: Db
) -> InvoiceRead:
    service.record_payment(
        session,
        principal,
        invoice_id,
        amount=data.amount,
        received_on=data.received_on,
        method=data.method,
        reference=data.reference,
    )
    session.commit()
    return service.to_staff_view(session, service.get_invoice(session, principal, invoice_id))


@router.post(
    "/{invoice_id}/payments/{payment_id}/reverse",
    status_code=status.HTTP_201_CREATED,
    summary="Reverse a payment entered by mistake (adds a reversal; nothing is deleted)",
    responses=problem_responses(404, 409, 422),
)
def reverse_payment(
    invoice_id: InvoiceId,
    payment_id: uuid.UUID,
    data: PaymentReversal,
    principal: Cashier,
    session: Db,
) -> InvoiceRead:
    service.reverse_payment(session, principal, invoice_id, payment_id, reason=data.reason)
    session.commit()
    return service.to_staff_view(session, service.get_invoice(session, principal, invoice_id))


@router.post(
    "/{invoice_id}/credit-notes",
    status_code=status.HTTP_201_CREATED,
    summary="Issue a credit note (reduces the amount still owed)",
    responses=problem_responses(404, 409, 422),
)
def issue_credit_note(
    invoice_id: InvoiceId, data: CreditNoteCreate, principal: Manager, session: Db
) -> InvoiceRead:
    service.issue_credit_note(session, principal, invoice_id, reason=data.reason, lines=data.lines)
    session.commit()
    return service.to_staff_view(session, service.get_invoice(session, principal, invoice_id))


# --- customer portal ----------------------------------------------------------------------

portal_router = APIRouter(
    prefix="/portal/invoices", tags=["portal"], responses=problem_responses(401, 403)
)
Customer = Annotated[Principal, Depends(require_any_permission(Permission.PORTAL_INVOICE_READ))]


@portal_router.get("", summary="My company's invoices (issued ones only)")
def my_invoices(
    principal: Customer,
    session: Db,
    account_id: uuid.UUID | None = None,
    order_id: uuid.UUID | None = None,
    state: InvoiceFilter | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[PortalInvoiceSummary]:
    return service.customer_invoices(
        session,
        principal,
        account_id=account_id,
        order_id=order_id,
        state=state,
        limit=limit,
        offset=offset,
    )


@portal_router.get(
    "/{invoice_id}",
    summary="One of my invoices: lines, credit notes, payments, amount owed",
    responses=problem_responses(404),
)
def my_invoice(invoice_id: InvoiceId, principal: Customer, session: Db) -> PortalInvoiceRead:
    return service.customer_invoice(session, principal, invoice_id)
