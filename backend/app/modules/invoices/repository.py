"""Database queries for invoices. Every query applies ``readable_invoices``."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import ColumnElement, Select, func, or_, select, text
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.search import escape_like
from app.modules.invoices.models import CreditNote, CreditNoteLine, Invoice, InvoiceLine, Payment
from app.modules.invoices.policies import readable_invoices

_SORTS = {"created_at": Invoice.created_at, "due_date": Invoice.due_date, "total": Invoice.total}


@dataclass(frozen=True)
class InvoiceFilters:
    q: str | None = None
    state: str | None = None
    account_id: uuid.UUID | None = None
    order_id: uuid.UUID | None = None
    sort: str = "-created_at"
    limit: int = 50
    offset: int = 0


def next_number(session: Session, tenant_id: uuid.UUID, series: str) -> int:
    """Next number of a series for this tenant. The counter row stays locked until the
    transaction ends, so concurrent issues wait, and a rollback gives the number back."""
    number = session.scalar(
        text(
            "INSERT INTO billing_number_counters (tenant_id, series, last_number) "
            "VALUES (:t, :s, 1) "
            "ON CONFLICT (tenant_id, series) DO UPDATE "
            "SET last_number = billing_number_counters.last_number + 1 "
            "RETURNING last_number"
        ),
        {"t": tenant_id, "s": series},
    )
    if number is None:
        raise RuntimeError("could not allocate a billing number")
    return int(number)


def _state_condition(state: str, today: date) -> ColumnElement[bool]:
    issued = Invoice.status == "issued"
    match state:
        case "draft" | "discarded":
            return Invoice.status == state
        case "unpaid":
            return issued & (Invoice.balance_due > 0)
        case "overdue":
            return issued & (Invoice.balance_due > 0) & (Invoice.due_date < today)
        case "paid":
            return issued & (Invoice.balance_due == 0)
    raise ValueError(f"unknown invoice filter {state!r}")


def _filtered(principal: Principal, filters: InvoiceFilters, today: date) -> Select[Invoice]:
    statement = select(Invoice).where(readable_invoices(principal))
    if filters.q:
        term = filters.q.strip()
        digits = term.upper().removeprefix("INV-").lstrip("0")
        conditions: list[ColumnElement[bool]] = [
            Invoice.customer_reference.ilike(f"%{escape_like(term)}%", escape="\\")
        ]
        if digits.isdigit() and len(digits) < 10:
            conditions.append(Invoice.number == int(digits))
        statement = statement.where(or_(*conditions))
    if filters.state:
        statement = statement.where(_state_condition(filters.state, today))
    if filters.account_id:
        statement = statement.where(Invoice.account_id == filters.account_id)
    if filters.order_id:
        statement = statement.where(Invoice.order_id == filters.order_id)
    return statement


def search(
    session: Session, principal: Principal, filters: InvoiceFilters, today: date
) -> tuple[Sequence[Invoice], int]:
    statement = _filtered(principal, filters, today)
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    column = _SORTS[filters.sort.lstrip("-")]
    order = column.desc() if filters.sort.startswith("-") else column.asc()
    page = (
        statement.order_by(order.nulls_last(), Invoice.id)
        .limit(filters.limit)
        .offset(filters.offset)
    )
    return session.scalars(page).all(), total


def get_readable(
    session: Session, principal: Principal, invoice_id: uuid.UUID, *, for_update: bool = False
) -> Invoice | None:
    statement = select(Invoice).where(Invoice.id == invoice_id, readable_invoices(principal))
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return session.scalars(statement).one_or_none()


def lines(session: Session, invoice: Invoice) -> Sequence[InvoiceLine]:
    return session.scalars(
        select(InvoiceLine)
        .where(InvoiceLine.tenant_id == invoice.tenant_id, InvoiceLine.invoice_id == invoice.id)
        .order_by(InvoiceLine.position)
    ).all()


def credit_notes(session: Session, invoice: Invoice) -> Sequence[CreditNote]:
    return session.scalars(
        select(CreditNote)
        .where(CreditNote.tenant_id == invoice.tenant_id, CreditNote.invoice_id == invoice.id)
        .order_by(CreditNote.number)
    ).all()


def credit_note_lines(
    session: Session, tenant_id: uuid.UUID, note_ids: Sequence[uuid.UUID]
) -> Sequence[CreditNoteLine]:
    if not note_ids:
        return []
    return session.scalars(
        select(CreditNoteLine)
        .where(CreditNoteLine.tenant_id == tenant_id, CreditNoteLine.credit_note_id.in_(note_ids))
        .order_by(CreditNoteLine.credit_note_id, CreditNoteLine.position)
    ).all()


def payments(session: Session, invoice: Invoice) -> Sequence[Payment]:
    return session.scalars(
        select(Payment)
        .where(Payment.tenant_id == invoice.tenant_id, Payment.invoice_id == invoice.id)
        .order_by(Payment.seq)
    ).all()


def get_payment(session: Session, invoice: Invoice, payment_id: uuid.UUID) -> Payment | None:
    return session.scalars(
        select(Payment).where(
            Payment.tenant_id == invoice.tenant_id,
            Payment.invoice_id == invoice.id,
            Payment.id == payment_id,
        )
    ).one_or_none()
