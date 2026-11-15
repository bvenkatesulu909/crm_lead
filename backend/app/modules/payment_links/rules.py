"""Pure rules for payment links (ADR 0031): no database, no network.

Money is a ``Decimal`` everywhere in the CRM; the only integer is *paise* at the edge, because that
is what Razorpay takes. The webhook signature is checked here, over the RAW bytes of the request.
"""

import hashlib
import hmac
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

LINK_STATUSES = ("created", "paid", "cancelled", "expired")

# What the worker decided about one verified event. ``None`` while it is still waiting.
EVENT_OUTCOMES = (
    "applied",  # the payment was added to the invoice
    "already_applied",  # the same Razorpay payment was seen before; nothing added
    "amount_mismatch",  # paid amount differs from the link: a person must look
    "currency_mismatch",
    "invoice_closed",  # the invoice no longer has a balance, or was cancelled
    "ignored",  # an event type we do not act on
)

CURRENCY = "INR"
DEFAULT_EXPIRY_DAYS = 7
# Razorpay: a reference id is unique per link, at most 40 characters.
REFERENCE_MAX_LENGTH = 40
# Razorpay's smallest payment is one rupee; the CRM never asks for more than ten crore.
MIN_PAISE = 100
MAX_PAISE = 10_00_00_000 * 100


def verify_signature(raw_body: bytes, signature: str | None, secret: str | None) -> bool:
    """True only when ``signature`` is the HMAC-SHA256 (hex) of ``raw_body`` under ``secret``.

    The body must be the bytes exactly as they arrived: parsing and re-writing the JSON changes
    them. The comparison takes the same time whatever the input. No secret means no way to verify,
    which is a refusal, never a pass."""
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


def sign(raw_body: bytes, secret: str) -> str:
    """The signature Razorpay would send. Used by tests and the fake provider only."""
    return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def body_sha256(raw_body: bytes) -> str:
    return hashlib.sha256(raw_body).hexdigest()


def to_paise(amount: Decimal) -> int:
    """Rupees to whole paise. Refuses zero, negatives, fractions of a paisa and absurd sizes."""
    if not isinstance(amount, Decimal) or not amount.is_finite():
        raise ValueError("The amount must be a decimal number.")
    paise = amount * 100
    if paise != paise.to_integral_value():
        raise ValueError("The amount can have at most two decimal places.")
    value = int(paise)
    if value < MIN_PAISE:
        raise ValueError("The amount is below the smallest payment (1 rupee).")
    if value > MAX_PAISE:
        raise ValueError("The amount is above the largest payment.")
    return value


def from_paise(paise: int) -> Decimal:
    return Decimal(paise) / 100


def reference_id(invoice_id: uuid.UUID, attempt: int) -> str:
    """A unique, short reference for a link: the invoice and which try this is (1-99)."""
    if not 1 <= attempt <= 99:
        raise ValueError("attempt must be between 1 and 99")
    return f"i{invoice_id.hex}{attempt:02d}"


def expires_at(now: datetime, days: int = DEFAULT_EXPIRY_DAYS) -> datetime:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now + timedelta(days=days)
