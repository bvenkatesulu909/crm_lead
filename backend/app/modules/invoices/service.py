"""Invoice business rules. Functions never commit; routers commit once per request.

Every money change locks the invoice row (SELECT ... FOR UPDATE) so two people recording a
payment at the same moment cannot both pay off the same balance. Every important change
writes an audit_log row in the same transaction.
"""

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.core.money import line_amounts, totals_of
from app.modules.identity import api as identity_api
from app.modules.invoices import repository
from app.modules.invoices.models import CreditNote, CreditNoteLine, Invoice, InvoiceLine, Payment
from app.modules.invoices.policies import can_manage, can_record_payments
from app.modules.invoices.repository import InvoiceFilters
from app.modules.invoices.rules import (
    DEFAULT_PAYMENT_TERMS_DAYS,
    INVOICEABLE_ORDER_STATUSES,
    InvoiceNotIssuedError,
    check_credit_amount,
    check_due_date,
    check_payment_amount,
    check_received_on,
    payment_state,
)
from app.modules.invoices.schemas import (
    CreditNoteLineInput,
    CreditNoteRead,
    InvoiceLineRead,
    InvoiceRead,
    InvoiceSummary,
    PaymentMethod,
    PaymentRead,
    PortalInvoiceRead,
    PortalInvoiceSummary,
    PortalPaymentRead,
)
from app.modules.orders import api as orders_api

ENTITY = "invoice"


class InvoiceNotFoundError(NotFoundError):
    code = "invoice_not_found"

    def __init__(self) -> None:
        super().__init__("Invoice not found.")


class PaymentNotFoundError(NotFoundError):
    code = "payment_not_found"

    def __init__(self) -> None:
        super().__init__("Payment not found.")


class InvoiceNotDraftError(ConflictError):
    code = "invoice_not_draft"


class OrderNotInvoiceableError(ConflictError):
    code = "order_not_invoiceable"


class OrderAlreadyInvoicedError(ConflictError):
    code = "order_already_invoiced"


class PaymentNotReversibleError(ConflictError):
    code = "payment_not_reversible"


class VersionConflictError(ConflictError):
    code = "version_conflict"


def _now() -> datetime:
    return datetime.now(UTC)


def _today() -> date:
    return _now().date()


def _tenant(principal: Principal) -> uuid.UUID:
    if principal.tenant_id is None:
        raise ForbiddenError("Only members of an organisation can use invoices.")
    return principal.tenant_id


def _flush(session: Session) -> None:
    try:
        session.flush()
    except StaleDataError as exc:
        raise VersionConflictError("The invoice was changed by someone else. Reload it.") from exc


def _audit(
    session: Session,
    principal: Principal,
    entity_id: uuid.UUID,
    action: str,
    changes: dict[str, object],
    entity_type: str = ENTITY,
) -> None:
    record_audit(
        session,
        principal,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        changes=changes,
    )


def _check_version(invoice: Invoice, version: int) -> None:
    if invoice.version != version:
        raise VersionConflictError(
            f"The invoice was changed by someone else (now version {invoice.version}). Reload it."
        )


# --- views --------------------------------------------------------------------------------


def _state(invoice: Invoice, today: date | None = None) -> str:
    return payment_state(
        status=invoice.status,
        total=invoice.total,
        amount_paid=invoice.amount_paid,
        amount_credited=invoice.amount_credited,
        balance_due=invoice.balance_due,
        due_date=invoice.due_date,
        today=today or _today(),
    )


def _columns(invoice: Invoice) -> dict[str, object]:
    return {c.key: getattr(invoice, c.key) for c in Invoice.__table__.columns}


def to_summary(invoice: Invoice, today: date | None = None) -> InvoiceSummary:
    return InvoiceSummary.model_validate(
        {**_columns(invoice), "payment_state": _state(invoice, today)}
    )


def _credit_notes_view(session: Session, invoice: Invoice) -> list[CreditNoteRead]:
    notes = repository.credit_notes(session, invoice)
    by_note: dict[uuid.UUID, list[InvoiceLineRead]] = defaultdict(list)
    for line in repository.credit_note_lines(session, invoice.tenant_id, [n.id for n in notes]):
        by_note[line.credit_note_id].append(InvoiceLineRead.model_validate(line))
    return [
        CreditNoteRead.model_validate(
            {
                "id": n.id,
                "number": n.number,
                "reason": n.reason,
                "issue_date": n.issue_date,
                "subtotal": n.subtotal,
                "tax_total": n.tax_total,
                "total": n.total,
                "lines": by_note[n.id],
            }
        )
        for n in notes
    ]


def _lines_view(session: Session, invoice: Invoice) -> list[InvoiceLineRead]:
    return [InvoiceLineRead.model_validate(line) for line in repository.lines(session, invoice)]


def to_staff_view(session: Session, invoice: Invoice) -> InvoiceRead:
    payments = repository.payments(session, invoice)
    reversed_ids = {p.reverses_payment_id for p in payments if p.reverses_payment_id}
    people = identity_api.people_by_id(
        session,
        invoice.tenant_id,
        {p.recorded_by_user_id for p in payments if p.recorded_by_user_id},
    )
    return InvoiceRead.model_validate(
        {
            **_columns(invoice),
            "payment_state": _state(invoice),
            "lines": _lines_view(session, invoice),
            "credit_notes": _credit_notes_view(session, invoice),
            "payments": [
                PaymentRead(
                    id=p.id,
                    amount=p.amount,
                    received_on=p.received_on,
                    method=cast(PaymentMethod, p.method),
                    reference=p.reference,
                    recorded_by_name=people.get(p.recorded_by_user_id, ("Former user", ""))[0]
                    if p.recorded_by_user_id
                    else "System",
                    reverses_payment_id=p.reverses_payment_id,
                    reversal_reason=p.reversal_reason,
                    reversed=p.id in reversed_ids,
                    created_at=p.created_at,
                )
                for p in payments
            ],
        }
    )


def to_portal_summary(invoice: Invoice) -> PortalInvoiceSummary:
    return PortalInvoiceSummary.model_validate(
        {**_columns(invoice), "payment_state": _state(invoice)}
    )


def to_portal_view(session: Session, invoice: Invoice) -> PortalInvoiceRead:
    payments = repository.payments(session, invoice)
    reversed_ids = {p.reverses_payment_id for p in payments if p.reverses_payment_id}
    # Customers see the payments that count: no reversal rows and no reversed payments.
    counted = [p for p in payments if p.reverses_payment_id is None and p.id not in reversed_ids]
    return PortalInvoiceRead.model_validate(
        {
            **_columns(invoice),
            "payment_state": _state(invoice),
            "lines": _lines_view(session, invoice),
            "credit_notes": _credit_notes_view(session, invoice),
            "payments": [
                PortalPaymentRead(
                    amount=p.amount,
                    received_on=p.received_on,
                    method=cast(PaymentMethod, p.method),
                    reference=p.reference,
                )
                for p in counted
            ],
        }
    )


# --- read ---------------------------------------------------------------------------------


def get_invoice(session: Session, principal: Principal, invoice_id: uuid.UUID) -> Invoice:
    invoice = repository.get_readable(session, principal, invoice_id)
    if invoice is None:
        raise InvoiceNotFoundError()
    return invoice


def list_invoices(
    session: Session, principal: Principal, filters: InvoiceFilters
) -> tuple[Sequence[Invoice], int]:
    return repository.search(session, principal, filters, _today())


# --- create, issue, discard ---------------------------------------------------------------


def create_from_order(session: Session, principal: Principal, order_id: uuid.UUID) -> Invoice:
    """A DRAFT invoice whose lines are a copy of the order's frozen lines."""
    tenant_id = _tenant(principal)
    if not can_manage(principal):
        raise ForbiddenError("You may not create invoices.")
    order = orders_api.order_for_invoicing(session, principal, order_id)
    if order is None:
        raise NotFoundError("Order not found.")
    if order.status not in INVOICEABLE_ORDER_STATUSES:
        raise OrderNotInvoiceableError(
            f"An order in status '{order.status}' cannot be invoiced. Confirm it first."
        )
    existing = session.scalar(
        select(Invoice.id).where(
            Invoice.tenant_id == tenant_id,
            Invoice.order_id == order.id,
            Invoice.status != "discarded",
        )
    )
    if existing is not None:
        raise OrderAlreadyInvoicedError("This order already has an invoice.")
    # Locks the order row and marks it, so it can no longer be cancelled. Fails if the order was
    # cancelled since we read it (a concurrent request).
    if not orders_api.mark_invoiced(
        session, principal, order.id, statuses=INVOICEABLE_ORDER_STATUSES
    ):
        raise OrderNotInvoiceableError("The order changed meanwhile and cannot be invoiced.")

    invoice = Invoice(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        order_id=order.id,
        account_id=order.account_id,
        created_by_user_id=principal.user_id,
        status="draft",
        currency=order.currency,
        customer_reference=order.customer_reference,
        subtotal=order.subtotal,
        tax_total=order.tax_total,
        total=order.total,
        amount_paid=0,
        amount_credited=0,
        balance_due=order.total,
    )
    session.add(invoice)
    try:
        session.flush()
    except IntegrityError as exc:  # a concurrent request invoiced the same order
        raise OrderAlreadyInvoicedError("This order already has an invoice.") from exc
    for line in order.lines:
        session.add(
            InvoiceLine(
                tenant_id=tenant_id,
                invoice_id=invoice.id,
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
        )
    _audit(
        session,
        principal,
        invoice.id,
        "invoice.created",
        {"order_id": order.id, "order_number": order.number, "total": order.total},
    )
    _flush(session)
    return invoice


def _load_for_change(
    session: Session, principal: Principal, invoice_id: uuid.UUID, *, allowed: bool, what: str
) -> Invoice:
    invoice = repository.get_readable(session, principal, invoice_id, for_update=True)
    if invoice is None:
        raise InvoiceNotFoundError()
    if not allowed:
        raise ForbiddenError(f"You may view this invoice but not {what}.")
    return invoice


def issue(
    session: Session,
    principal: Principal,
    invoice_id: uuid.UUID,
    *,
    version: int,
    due_date: date | None,
) -> Invoice:
    invoice = _load_for_change(
        session, principal, invoice_id, allowed=can_manage(principal), what="issue it"
    )
    if invoice.status != "draft":
        raise InvoiceNotDraftError("Only draft invoices can be issued.")
    _check_version(invoice, version)
    today = _today()
    due = due_date or today + timedelta(days=DEFAULT_PAYMENT_TERMS_DAYS)
    check_due_date(today, due)
    invoice.number = repository.next_number(session, invoice.tenant_id, "invoice")
    invoice.status = "issued"
    invoice.issue_date = today
    invoice.due_date = due
    invoice.issued_at = _now()
    _audit(
        session,
        principal,
        invoice.id,
        "invoice.issued",
        {"number": invoice.number, "total": invoice.total, "due_date": due},
    )
    _flush(session)
    return invoice


def discard(
    session: Session, principal: Principal, invoice_id: uuid.UUID, *, version: int
) -> Invoice:
    invoice = _load_for_change(
        session, principal, invoice_id, allowed=can_manage(principal), what="discard it"
    )
    if invoice.status != "draft":
        raise InvoiceNotDraftError(
            "Only drafts can be discarded. An issued invoice is corrected with a credit note."
        )
    _check_version(invoice, version)
    invoice.status = "discarded"
    invoice.discarded_at = _now()
    orders_api.release_invoiced(session, invoice.tenant_id, invoice.order_id)
    _audit(session, principal, invoice.id, "invoice.discarded", {})
    _flush(session)
    return invoice


# --- payments -----------------------------------------------------------------------------


def _require_issued(invoice: Invoice) -> None:
    if invoice.status != "issued":
        raise InvoiceNotIssuedError("Issue the invoice first.")


def record_payment(
    session: Session,
    principal: Principal,
    invoice_id: uuid.UUID,
    *,
    amount: Decimal,
    received_on: date,
    method: str,
    reference: str | None,
) -> Payment:
    invoice = _load_for_change(
        session,
        principal,
        invoice_id,
        allowed=can_record_payments(principal),
        what="record payments",
    )
    _require_issued(invoice)
    value = amount
    check_received_on(received_on, _today())
    check_payment_amount(value, invoice.balance_due)
    payment = Payment(
        tenant_id=invoice.tenant_id,
        invoice_id=invoice.id,
        amount=value,
        received_on=received_on,
        method=method,
        reference=reference,
        recorded_by_user_id=principal.user_id,
    )
    session.add(payment)
    invoice.amount_paid += value
    invoice.balance_due -= value
    _flush(session)
    _audit(
        session,
        principal,
        invoice.id,
        "payment.recorded",
        {"payment_id": payment.id, "amount": value, "method": method},
    )
    _flush(session)
    return payment


def reverse_payment(
    session: Session,
    principal: Principal,
    invoice_id: uuid.UUID,
    payment_id: uuid.UUID,
    *,
    reason: str,
) -> Payment:
    """Undo a payment entered by mistake (e.g. a bounced transfer). Nothing is deleted: a
    reversal row with the same amount is added, and the balance goes back up."""
    invoice = _load_for_change(
        session,
        principal,
        invoice_id,
        allowed=can_record_payments(principal),
        what="change payments",
    )
    original = repository.get_payment(session, invoice, payment_id)
    if original is None:
        raise PaymentNotFoundError()
    if original.reverses_payment_id is not None:
        raise PaymentNotReversibleError("A reversal cannot be reversed. Record a new payment.")
    already = session.scalar(
        select(Payment.id).where(
            Payment.tenant_id == invoice.tenant_id, Payment.reverses_payment_id == original.id
        )
    )
    if already is not None:
        raise PaymentNotReversibleError("This payment was already reversed.")
    reversal = Payment(
        tenant_id=invoice.tenant_id,
        invoice_id=invoice.id,
        amount=original.amount,
        received_on=_today(),
        method=original.method,
        reference=None,
        recorded_by_user_id=principal.user_id,
        reverses_payment_id=original.id,
        reversal_reason=reason,
    )
    session.add(reversal)
    invoice.amount_paid -= original.amount
    invoice.balance_due += original.amount
    _flush(session)
    _audit(
        session,
        principal,
        invoice.id,
        "payment.reversed",
        {"payment_id": original.id, "amount": original.amount, "reason": reason},
    )
    _flush(session)
    return reversal


# --- credit notes -------------------------------------------------------------------------


def issue_credit_note(
    session: Session,
    principal: Principal,
    invoice_id: uuid.UUID,
    *,
    reason: str,
    lines: Sequence[CreditNoteLineInput],
) -> CreditNote:
    invoice = _load_for_change(
        session, principal, invoice_id, allowed=can_manage(principal), what="credit it"
    )
    _require_issued(invoice)
    amounts = [line_amounts(i.quantity, i.unit_price, i.tax_rate) for i in lines]
    totals = totals_of(amounts)
    check_credit_amount(totals.total, invoice.balance_due)
    note = CreditNote(
        id=uuid.uuid4(),
        tenant_id=invoice.tenant_id,
        number=repository.next_number(session, invoice.tenant_id, "credit_note"),
        invoice_id=invoice.id,
        created_by_user_id=principal.user_id,
        reason=reason,
        issue_date=_today(),
        subtotal=totals.subtotal,
        tax_total=totals.tax_total,
        total=totals.total,
    )
    session.add(note)
    invoice.amount_credited += totals.total
    invoice.balance_due -= totals.total
    _flush(session)
    for position, (item, amount) in enumerate(zip(lines, amounts, strict=True), start=1):
        session.add(
            CreditNoteLine(
                tenant_id=invoice.tenant_id,
                credit_note_id=note.id,
                position=position,
                product_code=None,
                description=item.description,
                quantity=item.quantity,
                unit_price=item.unit_price,
                tax_rate=item.tax_rate,
                line_subtotal=amount.subtotal,
                line_tax=amount.tax,
                line_total=amount.total,
            )
        )
    _audit(
        session,
        principal,
        note.id,
        "credit_note.issued",
        {"invoice_id": invoice.id, "number": note.number, "total": totals.total},
        entity_type="credit_note",
    )
    _flush(session)
    return note


# --- customer (portal and AI assistant) ---------------------------------------------------


def _require_customer(principal: Principal) -> None:
    if principal.user_type != "customer" or not principal.has_permission(
        Permission.PORTAL_INVOICE_READ
    ):
        raise ForbiddenError("Only customers can use the portal invoice view.")


def customer_invoices(
    session: Session,
    principal: Principal,
    *,
    account_id: uuid.UUID | None = None,
    order_id: uuid.UUID | None = None,
    state: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[PortalInvoiceSummary]:
    _require_customer(principal)
    filters = InvoiceFilters(
        q=q, state=state, account_id=account_id, order_id=order_id, limit=limit, offset=offset
    )
    items, _ = repository.search(session, principal, filters, _today())
    return [to_portal_summary(i) for i in items]


def customer_invoice(
    session: Session, principal: Principal, invoice_id: uuid.UUID
) -> PortalInvoiceRead:
    _require_customer(principal)
    return to_portal_view(session, get_invoice(session, principal, invoice_id))
