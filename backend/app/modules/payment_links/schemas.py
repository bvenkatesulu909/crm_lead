"""Request and response shapes of the payment links API (ADR 0031)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

LinkState = Literal["created", "paid", "cancelled", "expired"]


class CreatePaymentLink(BaseModel):
    """Only the invoice. The amount, reference, expiry and who asked are decided by the server."""

    model_config = ConfigDict(extra="forbid")

    invoice_id: uuid.UUID


class PaymentLinkRead(BaseModel):
    id: uuid.UUID
    invoice_id: uuid.UUID
    short_url: str
    amount: Decimal
    currency: str
    status: LinkState
    expires_at: datetime
    created_at: datetime
    paid_at: datetime | None


class PaymentLinkList(BaseModel):
    items: list[PaymentLinkRead]
