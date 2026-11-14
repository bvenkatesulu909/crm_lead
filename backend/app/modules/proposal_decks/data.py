"""The plain data a proposal deck is drawn from (ADR 0032, PD2). Built by the caller (PD3) from the
quote and the organisation's branding; the renderer never reads a database."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class DeckBrand:
    organisation: str
    color: str  # six lower-case hex digits, already checked by the branding module
    about_text: str
    terms_text: str
    contact_line: str
    footer_line: str
    logo_png: bytes | None


@dataclass(frozen=True)
class DeckLine:
    position: int
    description: str
    quantity: Decimal
    unit: str
    net_unit_price: Decimal
    discount_percent: Decimal
    tax_rate: Decimal
    line_subtotal: Decimal


@dataclass(frozen=True)
class DeckData:
    number: str  # "QT-0007" or "QT-0007 rev 2"
    title: str
    customer: str
    contact: str | None
    issued: date
    valid_until: date
    currency: str
    lines: tuple[DeckLine, ...]
    gross_total: Decimal
    discount_total: Decimal
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    customer_note: str | None
    brand: DeckBrand
