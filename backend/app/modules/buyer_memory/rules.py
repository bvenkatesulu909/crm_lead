"""Pure rules of buyer memory (ADR 0028): the vocabulary, what a row must contain, cleaning,
and how rows become "current / history / gaps". No database, no model, no network.

A detail is a **fact** (the buyer said it or confirmed it, and we say where and quote them) or an
**assumption** (we think so, and say why). A **gap** is a key with no current row - it is worked
out, never stored.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from app.core.screening import screen
from app.modules.assistant import api as assistant_api

MAX_TEXT = 300


@dataclass(frozen=True)
class MemoryKey:
    key: str
    label: str


# The fixed list (BM2). Nothing here invites sensitive categories (religion, caste, health, ...).
KEYS: tuple[MemoryKey, ...] = (
    MemoryKey("budget", "Budget"),
    MemoryKey("property_type", "Property type"),
    MemoryKey("location", "Area or location"),
    MemoryKey("timeline", "When they want to buy"),
    MemoryKey("purpose", "Own use or investment"),
    MemoryKey("financing", "Financing"),
    MemoryKey("household", "Who will live there"),
    MemoryKey("decision_makers", "Who decides"),
    MemoryKey("must_haves", "Must-haves"),
    MemoryKey("deal_breakers", "Deal-breakers"),
    MemoryKey("current_home", "Where they live now"),
    MemoryKey("other_options", "Other projects they are looking at"),
)
KEY_NAMES = tuple(k.key for k in KEYS)

STATUSES = ("fact", "assumption")
# Where a fact may come from. Code (the website chat, the copy button) may use all four; the API
# only the two a person can vouch for.
SOURCES = ("website_chat", "timeline_entry", "lead_record", "buyer_confirmed")
API_SOURCES = ("timeline_entry", "buyer_confirmed")
# Sources that are pointed at by id (a timeline entry of this lead, a website conversation).
SOURCE_NEEDS_REF = ("timeline_entry", "website_chat")


class MemoryRuleError(ValueError):
    """A row that breaks a rule. ``field`` names what is wrong; ``refused`` is True when the text
    itself was refused (a card number, an instruction to an AI) rather than just malformed."""

    def __init__(self, field: str, message: str, *, refused: bool = False) -> None:
        super().__init__(message)
        self.field = field
        self.refused = refused


@dataclass(frozen=True)
class NewItem:
    key: str
    value: str
    status: str
    source: str | None
    source_ref: uuid.UUID | None
    quote: str | None
    reason: str | None


def _text(field: str, raw: object, *, required: bool) -> str | None:
    if raw is None:
        if required:
            raise MemoryRuleError(field, f"{field} is required.")
        return None
    if not isinstance(raw, str):
        raise MemoryRuleError(field, f"{field} must be text.")
    if len(raw) > MAX_TEXT * 4:
        raise MemoryRuleError(field, f"{field} is too long (at most {MAX_TEXT} characters).")
    if not raw.strip():
        if required:
            raise MemoryRuleError(field, f"{field} is required.")
        return None
    # The same screening as a visitor's message: a card number or an instruction to an AI is
    # refused; links, images, markup and hidden characters are then taken out (ADR 0028, BM7).
    decision = assistant_api.inspect_input(raw)
    if not decision.allowed:
        raise MemoryRuleError(field, f"The {field} was refused: {decision.reason}", refused=True)
    cleaned = screen(decision.clean, strip_links=True, strip_addresses=False).clean
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        if required:
            raise MemoryRuleError(field, f"{field} is empty once cleaned.")
        return None
    if len(cleaned) > MAX_TEXT:
        raise MemoryRuleError(field, f"{field} is too long (at most {MAX_TEXT} characters).")
    return cleaned


def check_new_item(
    *,
    key: object,
    value: object,
    status: object,
    source: object = None,
    source_ref: uuid.UUID | None = None,
    quote: object = None,
    reason: object = None,
) -> NewItem:
    """Validate and clean one row. Raises :class:`MemoryRuleError`."""
    if not isinstance(key, str) or key not in KEY_NAMES:
        raise MemoryRuleError("key", "key must be one of the twelve buyer memory keys.")
    if not isinstance(status, str) or status not in STATUSES:
        raise MemoryRuleError("status", "status must be 'fact' or 'assumption'.")
    if source is not None and (not isinstance(source, str) or source not in SOURCES):
        raise MemoryRuleError("source", "source is not one of the allowed sources.")
    clean_value = _text("value", value, required=True)
    assert clean_value is not None  # noqa: S101 - required=True raises instead of returning None

    if status == "fact":
        if source is None:
            raise MemoryRuleError("source", "A fact needs a source: where did the buyer say it?")
        clean_quote = _text("quote", quote, required=False)
        if clean_quote is None:
            raise MemoryRuleError("quote", "A fact needs a quote of what the buyer said.")
        if reason is not None and str(reason).strip():
            raise MemoryRuleError("reason", "A fact has no reason - give a source and a quote.")
        clean_reason = None
    else:
        if source_ref is not None:
            raise MemoryRuleError(
                "source_ref", "An assumption has no source_ref - confirm it to make it a fact."
            )
        if source is not None or quote not in (None, ""):
            raise MemoryRuleError(
                "source",
                "An assumption points at no source - state a reason; confirm it to make it a fact.",
            )
        clean_reason = _text("reason", reason, required=False)
        if clean_reason is None:
            raise MemoryRuleError("reason", "An assumption needs a reason: why do we think so?")
        clean_quote = None

    if source in SOURCE_NEEDS_REF and source_ref is None:
        raise MemoryRuleError("source_ref", f"source_ref is needed for the source '{source}'.")
    if source not in SOURCE_NEEDS_REF and source_ref is not None:
        raise MemoryRuleError(
            "source_ref", "source_ref is only for a timeline entry or a conversation."
        )
    return NewItem(key, clean_value, status, source, source_ref, clean_quote, clean_reason)


class _Row(Protocol):
    seq: int
    key: str


@dataclass(frozen=True)
class Arranged:
    current: list[Any]
    history: list[Any]
    gaps: list[MemoryKey]


def arrange(rows: Sequence[Any]) -> Arranged:
    """The newest row of each key is current (in the order of the key list); older rows are the
    history, newest first; every key without a current row is a gap."""
    newest: dict[str, Any] = {}
    for row in sorted(rows, key=lambda r: r.seq):
        newest[row.key] = row
    order = {name: i for i, name in enumerate(KEY_NAMES)}
    current = sorted(newest.values(), key=lambda r: order[r.key])
    kept = {id(r) for r in current}
    history = sorted((r for r in rows if id(r) not in kept), key=lambda r: r.seq, reverse=True)
    gaps = [k for k in KEYS if k.key not in newest]
    return Arranged(current, history, gaps)


# --- the lead form, written the way people say it ------------------------------------------------

_CRORE = Decimal(10_000_000)
_LAKH = Decimal(100_000)


def _rupees(value: int) -> str:
    amount = Decimal(value)
    if amount >= _CRORE:
        return f"{format((amount / _CRORE).normalize(), 'f')} Cr"
    if amount >= _LAKH:
        return f"{format((amount / _LAKH).normalize(), 'f')} L"
    return str(value)


def budget_text(low: int | None, high: int | None) -> str | None:
    """ "1.2 Cr - 1.5 Cr", "from 80 L", "up to 2 Cr", "1 Cr", or None when nothing is known."""
    if low is not None and high is not None:
        return _rupees(low) if low == high else f"{_rupees(low)} - {_rupees(high)}"
    if low is not None:
        return f"from {_rupees(low)}"
    if high is not None:
        return f"up to {_rupees(high)}"
    return None


_PROPERTY_TYPES = {
    "apartment": "Apartment",
    "villa": "Villa",
    "plot": "Plot",
    "commercial": "Commercial",
}


def property_type_text(value: str | None) -> str | None:
    return _PROPERTY_TYPES.get(value) if value else None
