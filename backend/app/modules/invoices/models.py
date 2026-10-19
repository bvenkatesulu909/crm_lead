"""Invoice tables.

- ``invoices``: created from an order as a DRAFT (no number yet). Issuing gives it the next
  gapless number and freezes it; a database trigger (migration 0006) refuses any later change
  except the running balance (amount_paid, amount_credited, balance_due).
- ``invoice_lines``: snapshot of the order lines. Insert-only for the application.
- ``credit_notes`` / ``credit_note_lines``: reduce what the customer owes. Insert-only.
- ``payments``: money received (entered manually). Insert-only; a mistake is corrected by a
  REVERSAL row that points at the original payment.
- ``billing_number_counters``: last number per tenant and series ("invoice", "credit_note").
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import (
    Base,
    TenantOwnedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    VersionedMixin,
)

INVOICE_STATUSES = ("draft", "issued", "discarded")
PAYMENT_METHODS = ("bank_transfer", "card", "cash", "other")
SERIES = ("invoice", "credit_note")


def _money() -> Mapped[Decimal]:
    return mapped_column(Numeric(18, 2))


class Invoice(UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "number"),
        ForeignKeyConstraint(
            ["tenant_id", "account_id"], ["accounts.tenant_id", "accounts.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "order_id"], ["orders.tenant_id", "orders.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(f"status IN {INVOICE_STATUSES}", name="status_allowed"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso"),
        CheckConstraint("number IS NULL OR number > 0", name="number_positive"),
        # A number, issue date and due date exist exactly when the invoice was issued.
        CheckConstraint(
            "(status = 'issued') = (number IS NOT NULL AND issue_date IS NOT NULL "
            "AND due_date IS NOT NULL AND issued_at IS NOT NULL)",
            name="issued_consistent",
        ),
        CheckConstraint("due_date >= issue_date", name="due_after_issue"),
        CheckConstraint(
            "subtotal >= 0 AND tax_total >= 0 AND total = subtotal + tax_total",
            name="totals_consistent",
        ),
        CheckConstraint(
            "amount_paid >= 0 AND amount_credited >= 0 AND balance_due >= 0 "
            "AND balance_due = total - amount_paid - amount_credited",
            name="balance_consistent",
        ),
        # One live invoice per order (a discarded draft frees the order again).
        Index(
            "uq_invoices_tenant_id_order_id_live",
            "tenant_id",
            "order_id",
            unique=True,
            postgresql_where=text("status <> 'discarded'"),
        ),
        Index("ix_invoices_tenant_id_account_id", "tenant_id", "account_id"),
        Index("ix_invoices_tenant_id_status_due_date", "tenant_id", "status", "due_date"),
    )

    number: Mapped[int | None] = mapped_column(Integer)
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(20), server_default=text("'draft'"))
    currency: Mapped[str] = mapped_column(String(3))
    customer_reference: Mapped[str | None] = mapped_column(String(100))
    issue_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    issued_at: Mapped[datetime | None] = mapped_column(default=None)
    discarded_at: Mapped[datetime | None] = mapped_column(default=None)
    subtotal: Mapped[Decimal] = _money()
    tax_total: Mapped[Decimal] = _money()
    total: Mapped[Decimal] = _money()
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    amount_credited: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    balance_due: Mapped[Decimal] = _money()


class _LineColumns:
    position: Mapped[int] = mapped_column(Integer)
    product_code: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    line_subtotal: Mapped[Decimal] = _money()
    line_tax: Mapped[Decimal] = _money()
    line_total: Mapped[Decimal] = _money()


def _line_checks() -> tuple[CheckConstraint, ...]:
    return (
        CheckConstraint("position > 0", name="position_positive"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_not_negative"),
        CheckConstraint("tax_rate >= 0 AND tax_rate <= 100", name="tax_rate_range"),
        CheckConstraint("line_total = line_subtotal + line_tax", name="line_total_consistent"),
    )


class InvoiceLine(UUIDPrimaryKeyMixin, TenantOwnedMixin, _LineColumns, Base):
    __tablename__ = "invoice_lines"
    __table_args__ = (
        UniqueConstraint("tenant_id", "invoice_id", "position"),
        ForeignKeyConstraint(
            ["tenant_id", "invoice_id"], ["invoices.tenant_id", "invoices.id"], ondelete="RESTRICT"
        ),
        *_line_checks(),
    )

    invoice_id: Mapped[uuid.UUID] = mapped_column(Uuid)


class CreditNote(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    __tablename__ = "credit_notes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "number"),
        ForeignKeyConstraint(
            ["tenant_id", "invoice_id"], ["invoices.tenant_id", "invoices.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("number > 0", name="number_positive"),
        CheckConstraint(
            "subtotal >= 0 AND tax_total >= 0 AND total > 0 AND total = subtotal + tax_total",
            name="totals_consistent",
        ),
        Index("ix_credit_notes_tenant_id_invoice_id", "tenant_id", "invoice_id"),
    )

    number: Mapped[int] = mapped_column(Integer)
    invoice_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reason: Mapped[str] = mapped_column(String(500))
    issue_date: Mapped[date] = mapped_column(Date)
    subtotal: Mapped[Decimal] = _money()
    tax_total: Mapped[Decimal] = _money()
    total: Mapped[Decimal] = _money()
    created_at: Mapped[datetime] = mapped_column(server_default=func.clock_timestamp())


class CreditNoteLine(UUIDPrimaryKeyMixin, TenantOwnedMixin, _LineColumns, Base):
    __tablename__ = "credit_note_lines"
    __table_args__ = (
        UniqueConstraint("tenant_id", "credit_note_id", "position"),
        ForeignKeyConstraint(
            ["tenant_id", "credit_note_id"],
            ["credit_notes.tenant_id", "credit_notes.id"],
            ondelete="RESTRICT",
        ),
        *_line_checks(),
    )

    credit_note_id: Mapped[uuid.UUID] = mapped_column(Uuid)


class Payment(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "invoice_id"], ["invoices.tenant_id", "invoices.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "recorded_by_user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "reverses_payment_id"],
            ["payments.tenant_id", "payments.id"],
            ondelete="RESTRICT",
        ),
        # A payment can be reversed at most once.
        UniqueConstraint("tenant_id", "reverses_payment_id"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(f"method IN {PAYMENT_METHODS}", name="method_allowed"),
        CheckConstraint(
            "(reverses_payment_id IS NULL) = (reversal_reason IS NULL)",
            name="reversal_consistent",
        ),
        Index("ix_payments_tenant_id_invoice_id_seq", "tenant_id", "invoice_id", "seq"),
    )

    invoice_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    amount: Mapped[Decimal] = _money()
    received_on: Mapped[date] = mapped_column(Date)
    method: Mapped[str] = mapped_column(String(20))
    reference: Mapped[str | None] = mapped_column(String(100))
    recorded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reverses_payment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reversal_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(server_default=func.clock_timestamp())
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))


class BillingNumberCounter(Base):
    """Last number used per tenant and series. Taken inside the issuing transaction, so a
    rolled-back issue gives its number back: invoice numbers have no gaps."""

    __tablename__ = "billing_number_counters"
    __table_args__ = (CheckConstraint(f"series IN {SERIES}", name="series_allowed"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="RESTRICT"), primary_key=True
    )
    series: Mapped[str] = mapped_column(String(20), primary_key=True)
    last_number: Mapped[int] = mapped_column(Integer)
