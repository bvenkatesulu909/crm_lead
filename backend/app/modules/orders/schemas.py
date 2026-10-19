"""Request/response contracts for orders.

Input schemas never contain server-controlled fields: number, status, totals, line amounts,
created_by and timestamps are always set by the server. Staff and customers get DIFFERENT
response models: customers never receive internal notes, the creator or the history notes.
Money is sent as decimal STRINGS (e.g. "19.99") so no precision is lost in JSON.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

OrderStatus = Literal["draft", "confirmed", "in_fulfilment", "shipped", "delivered", "cancelled"]
OrderSort = Literal["-created_at", "created_at", "-updated_at", "-total"]

Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
ProductCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
Tracking = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]

MAX_LINES = 100


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OrderLineInput(_Input):
    product_code: ProductCode | None = None
    description: Description
    quantity: Annotated[Decimal, Field(gt=0, le=1_000_000, decimal_places=3)]
    unit_price: Annotated[Decimal, Field(ge=0, le=1_000_000_000, decimal_places=2)]
    tax_rate: Annotated[Decimal, Field(ge=0, le=100, decimal_places=2)] = Decimal("0")


class OrderCreate(_Input):
    account_id: uuid.UUID
    currency: Currency = "EUR"
    customer_reference: ShortText | None = None
    expected_delivery_date: date | None = None
    internal_note: Note | None = None
    lines: list[OrderLineInput] = Field(default_factory=list, max_length=MAX_LINES)


class OrderUpdate(_Input):
    """Replaces the whole draft (header and all lines). Only drafts can be edited."""

    version: int = Field(ge=1)
    currency: Currency
    customer_reference: ShortText | None = None
    expected_delivery_date: date | None = None
    internal_note: Note | None = None
    lines: list[OrderLineInput] = Field(max_length=MAX_LINES)


class OrderStatusChange(_Input):
    status: Literal["confirmed", "in_fulfilment", "shipped", "delivered", "cancelled"]
    version: int = Field(ge=1)
    reason: Reason | None = Field(
        default=None, description="Required for cancelled. The CUSTOMER sees this reason."
    )
    note: Note | None = Field(default=None, description="Staff-only note in the history.")
    tracking_reference: Tracking | None = Field(default=None, description="Only for shipped.")
    expected_delivery_date: date | None = Field(
        default=None, description="Only for confirmed, in_fulfilment or shipped."
    )

    @model_validator(mode="after")
    def _fields_match_status(self) -> "OrderStatusChange":
        if self.status == "cancelled" and self.reason is None:
            raise ValueError("A reason is required to cancel an order.")
        if self.status != "cancelled" and self.reason is not None:
            raise ValueError("A reason is only used when cancelling.")
        if self.status != "shipped" and self.tracking_reference is not None:
            raise ValueError("A tracking reference can only be set when shipping.")
        if self.status in ("delivered", "cancelled") and self.expected_delivery_date is not None:
            raise ValueError("An expected delivery date cannot be set for this status.")
        return self


class _Output(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class OrderLineRead(_Output):
    position: int
    product_code: str | None
    description: str
    quantity: Decimal
    unit_price: Decimal
    tax_rate: Decimal
    line_subtotal: Decimal
    line_tax: Decimal
    line_total: Decimal


class OrderEventRead(BaseModel):
    from_status: OrderStatus | None
    to_status: OrderStatus
    actor_name: str
    note: str | None
    created_at: datetime


class OrderSummary(_Output):
    """Staff list row."""

    id: uuid.UUID
    number: int
    account_id: uuid.UUID
    status: OrderStatus
    currency: str
    customer_reference: str | None
    total: Decimal
    expected_delivery_date: date | None
    created_at: datetime
    updated_at: datetime


class OrderPage(BaseModel):
    items: list[OrderSummary]
    total: int
    limit: int
    offset: int


class OrderRead(OrderSummary):
    """Staff detail view."""

    created_by_user_id: uuid.UUID | None
    internal_note: str | None
    tracking_reference: str | None
    subtotal: Decimal
    tax_total: Decimal
    confirmed_at: datetime | None
    shipped_at: datetime | None
    delivered_at: datetime | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    version: int
    lines: list[OrderLineRead]
    events: list[OrderEventRead]


class PortalOrderSummary(_Output):
    """Customer list row: no internal data."""

    id: uuid.UUID
    number: int
    account_id: uuid.UUID
    status: OrderStatus
    currency: str
    customer_reference: str | None
    total: Decimal
    expected_delivery_date: date | None
    confirmed_at: datetime | None


class PortalOrderStep(BaseModel):
    status: OrderStatus
    at: datetime


class PortalOrderRead(PortalOrderSummary):
    """Customer detail view: lines, totals, tracking and a status timeline WITHOUT staff notes
    or who changed what."""

    subtotal: Decimal
    tax_total: Decimal
    tracking_reference: str | None
    shipped_at: datetime | None
    delivered_at: datetime | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    lines: list[OrderLineRead]
    timeline: list[PortalOrderStep]
