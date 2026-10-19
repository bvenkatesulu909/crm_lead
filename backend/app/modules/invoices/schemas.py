"""Request/response contracts for invoices, credit notes and payments.

Inputs never contain server-controlled fields: numbers, statuses, totals, balances, the
customer account and the lines of an invoice always come from the server (the order).
Customers get smaller response models: no creator, no recorder, no payment reversal reasons.
Money is sent as decimal STRINGS ("19.99").
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

InvoiceStatus = Literal["draft", "issued", "discarded"]
PaymentStateName = Literal[
    "draft", "discarded", "open", "partially_paid", "overdue", "paid", "credited"
]
PaymentMethod = Literal["bank_transfer", "card", "cash", "other"]
InvoiceFilter = Literal["draft", "unpaid", "overdue", "paid", "discarded"]
InvoiceSort = Literal["-created_at", "created_at", "due_date", "-total"]

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
Reference = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Positive = Annotated[Decimal, Field(gt=0, le=1_000_000_000, decimal_places=2)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InvoiceFromOrder(_Input):
    order_id: uuid.UUID


class InvoiceIssue(_Input):
    version: int = Field(ge=1)
    due_date: date | None = Field(
        default=None, description="Defaults to 14 days after today. At most 365 days."
    )


class InvoiceDiscard(_Input):
    version: int = Field(ge=1)


class PaymentCreate(_Input):
    amount: Positive
    received_on: date
    method: PaymentMethod
    reference: Reference | None = Field(default=None, description="e.g. the bank reference")


class PaymentReversal(_Input):
    reason: Reason


class CreditNoteLineInput(_Input):
    description: Description
    quantity: Annotated[Decimal, Field(gt=0, le=1_000_000, decimal_places=3)] = Decimal("1")
    unit_price: Positive
    tax_rate: Annotated[Decimal, Field(ge=0, le=100, decimal_places=2)] = Decimal("0")


class CreditNoteCreate(_Input):
    reason: Reason = Field(description="Shown to the customer.")
    lines: list[CreditNoteLineInput] = Field(min_length=1, max_length=100)


class _Output(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class InvoiceLineRead(_Output):
    position: int
    product_code: str | None
    description: str
    quantity: Decimal
    unit_price: Decimal
    tax_rate: Decimal
    line_subtotal: Decimal
    line_tax: Decimal
    line_total: Decimal


class CreditNoteRead(_Output):
    id: uuid.UUID
    number: int
    reason: str
    issue_date: date
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    lines: list[InvoiceLineRead]


class PaymentRead(_Output):
    """Staff view of a payment or a reversal."""

    id: uuid.UUID
    amount: Decimal
    received_on: date
    method: PaymentMethod
    reference: str | None
    recorded_by_name: str
    reverses_payment_id: uuid.UUID | None
    reversal_reason: str | None
    reversed: bool
    created_at: datetime


class InvoiceSummary(_Output):
    id: uuid.UUID
    number: int | None
    order_id: uuid.UUID
    account_id: uuid.UUID
    status: InvoiceStatus
    payment_state: PaymentStateName
    currency: str
    total: Decimal
    balance_due: Decimal
    issue_date: date | None
    due_date: date | None
    created_at: datetime


class InvoicePage(BaseModel):
    items: list[InvoiceSummary]
    total: int
    limit: int
    offset: int


class InvoiceRead(InvoiceSummary):
    """Staff detail view."""

    customer_reference: str | None
    created_by_user_id: uuid.UUID | None
    issued_at: datetime | None
    discarded_at: datetime | None
    subtotal: Decimal
    tax_total: Decimal
    amount_paid: Decimal
    amount_credited: Decimal
    version: int
    lines: list[InvoiceLineRead]
    credit_notes: list[CreditNoteRead]
    payments: list[PaymentRead]


class PortalPaymentRead(BaseModel):
    """What the customer sees of a payment: only the ones that count (no reversed ones)."""

    amount: Decimal
    received_on: date
    method: PaymentMethod
    reference: str | None


class PortalInvoiceSummary(_Output):
    id: uuid.UUID
    number: int
    order_id: uuid.UUID
    account_id: uuid.UUID
    payment_state: PaymentStateName
    currency: str
    total: Decimal
    balance_due: Decimal
    issue_date: date
    due_date: date


class PortalInvoiceRead(PortalInvoiceSummary):
    customer_reference: str | None
    subtotal: Decimal
    tax_total: Decimal
    amount_paid: Decimal
    amount_credited: Decimal
    lines: list[InvoiceLineRead]
    credit_notes: list[CreditNoteRead]
    payments: list[PortalPaymentRead]
