"""Request and response shapes for quotes.

Prices, discounts in money, totals, numbers, statuses and approval data are server-controlled:
a client sends products, quantities and discount PERCENTAGES only.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.validation import Reason

MAX_LINES = 100
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
QuoteStatus = Literal[
    "draft", "pending_approval", "approved", "sent", "accepted", "declined", "superseded"
]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuoteLineInput(_Input):
    product_id: uuid.UUID = Field(description="A product in the quote's price book.")
    quantity: Annotated[Decimal, Field(gt=0, le=1_000_000, decimal_places=3)]
    discount_percent: Annotated[Decimal, Field(ge=0, le=100, decimal_places=2)] = Decimal("0")
    description: Description | None = Field(
        default=None, description="Optional; defaults to the product name."
    )


class QuoteCreate(_Input):
    account_id: uuid.UUID
    title: Title
    price_book_id: uuid.UUID = Field(description="Prices (and the currency) come from here.")
    opportunity_id: uuid.UUID | None = Field(
        default=None, description="A deal of the same account."
    )
    contact_id: uuid.UUID | None = Field(default=None, description="A contact of the same account.")
    owner_id: uuid.UUID | None = None
    valid_until: date | None = Field(default=None, description="Default: 30 days from today.")
    customer_note: LongText | None = None
    internal_note: LongText | None = None
    lines: list[QuoteLineInput] = Field(default_factory=list, max_length=MAX_LINES)


class QuoteUpdate(_Input):
    """Change a DRAFT. ``lines`` replaces all lines; changing the price book re-prices them."""

    version: int = Field(ge=1)
    title: Title | None = None
    price_book_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    valid_until: date | None = None
    customer_note: LongText | None = None
    internal_note: LongText | None = None
    lines: list[QuoteLineInput] | None = Field(default=None, max_length=MAX_LINES)

    @model_validator(mode="after")
    def _check(self) -> "QuoteUpdate":
        if not self.model_fields_set - {"version"}:
            raise ValueError("send at least one field to change")
        for required in ("title", "price_book_id", "valid_until", "lines"):
            if required in self.model_fields_set and getattr(self, required) is None:
                raise ValueError(f"{required} cannot be removed")
        return self


class Step(_Input):
    version: int = Field(ge=1)
    note: Reason | None = None


class EmailQuote(_Input):
    version: int = Field(ge=1)
    message: Reason | None = Field(
        default=None, description="Personal message in the e-mail (kept in the quote history)."
    )


class StepWithReason(_Input):
    version: int = Field(ge=1)
    reason: Reason


class ConvertToOrder(_Input):
    version: int = Field(ge=1)
    customer_reference: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None
    ) = None


class QuoteLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    position: int
    product_id: uuid.UUID
    sku: str
    description: str
    unit: str
    quantity: Decimal
    list_price: Decimal
    discount_percent: Decimal
    net_unit_price: Decimal
    tax_rate: Decimal
    line_gross: Decimal
    line_discount: Decimal
    line_subtotal: Decimal
    line_tax: Decimal
    line_total: Decimal


class _QuoteCore(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: int
    revision: int
    title: str
    account_id: uuid.UUID
    currency: str
    status: QuoteStatus
    valid_until: date
    expired: bool = Field(description="Sent but past its validity date.")
    customer_note: str | None
    gross_total: Decimal
    discount_total: Decimal
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    sent_at: datetime | None
    decided_at: datetime | None
    created_at: datetime
    version: int = Field(description="Send it back when accepting or declining.")


class QuoteSummary(_QuoteCore):
    opportunity_id: uuid.UUID | None
    owner_id: uuid.UUID | None
    needs_approval: bool
    max_discount_percent: Decimal
    order_id: uuid.UUID | None
    updated_at: datetime


class QuoteRead(QuoteSummary):
    revision_of_id: uuid.UUID | None
    contact_id: uuid.UUID | None
    created_by_user_id: uuid.UUID | None
    price_book_id: uuid.UUID
    internal_note: str | None
    submitted_at: datetime | None
    approved_at: datetime | None
    approved_by_user_id: uuid.UUID | None
    decision_note: str | None
    lines: list[QuoteLineRead]
    email_status: Literal["sending", "sent", "failed"] | None = Field(
        default=None, description="Newest e-mail of this quote (None: never e-mailed)."
    )


class QuotePage(BaseModel):
    items: list[QuoteSummary]
    total: int
    limit: int
    offset: int


class QuoteEventRead(BaseModel):
    from_status: str | None
    to_status: str
    note: str | None
    created_at: datetime
    actor_name: str | None


class PortalQuoteRead(_QuoteCore):
    """What the customer sees: no owner, approval details or internal notes."""

    decision_note: str | None
    lines: list[QuoteLineRead]


class PortalQuoteSummary(_QuoteCore):
    """A quote in the customer's list."""


class PortalQuotePage(BaseModel):
    items: list[PortalQuoteSummary]
    total: int


class QuoteSettingsRead(BaseModel):
    approval_limit_percent: Decimal = Field(
        description="Line discounts ABOVE this percentage need a manager's approval."
    )
    version: int = Field(description="0 while the organisation still uses the defaults.")
    updated_at: datetime | None


class QuoteSettingsUpdate(_Input):
    version: int = Field(ge=0, description="The version you read (0 for the defaults).")
    approval_limit_percent: Annotated[Decimal, Field(ge=0, le=100, decimal_places=2)]
