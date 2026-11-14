"""Pure helpers for the proposal deck (ADR 0032, PD2): money, number and date words, line paging and
the "can the font draw this?" filter. No database, no drawing."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

LINES_PER_SLIDE = 10
RUPEE = "₹"
UNKNOWN = "?"


def _lakh_grouping(whole: str) -> str:
    """12345678 -> 1,23,45,678 (the Indian way: the last three digits, then pairs)."""
    if len(whole) <= 3:
        return whole
    head, tail = whole[:-3], whole[-3:]
    groups: list[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join([*groups, tail])


def money(amount: Decimal, currency: str) -> str:
    """Rupees get the rupee sign and lakh grouping; any other currency keeps its code
    ("1,234.50 EUR"). Always two decimals, a minus sign for negative amounts."""
    cents = amount.quantize(Decimal("0.01"))
    sign = "-" if cents < 0 else ""
    whole, _, fraction = f"{abs(cents):.2f}".partition(".")
    if currency == "INR":
        return f"{sign}{RUPEE}{_lakh_grouping(whole)}.{fraction}"
    return f"{sign}{int(whole):,}.{fraction} {currency}"


def plain_number(value: Decimal) -> str:
    """2.500 -> "2.5", 10.00 -> "10": quantities without trailing zeros."""
    return f"{value.normalize():f}"


def long_date(day: date) -> str:
    return f"{day.day} {day.strftime('%B %Y')}"


def pages[T](items: Sequence[T], per_page: int = LINES_PER_SLIDE) -> list[list[T]]:
    """Split lines over slides, ``per_page`` each; an empty list still gives one (empty) slide."""
    if per_page < 1:
        raise ValueError("per_page must be at least 1")
    if not items:
        return [[]]
    return [list(items[i : i + per_page]) for i in range(0, len(items), per_page)]


def printable(text: str, can_draw: "set[int] | frozenset[int]") -> str:
    """Replace every character the font has no picture for by ``?``, so a deck never shows empty
    boxes. Line breaks stay. The font is Latin: Hindi and Telugu are a later step (ADR 0032)."""
    return "".join(ch if ch in ("\n", " ") or ord(ch) in can_draw else UNKNOWN for ch in text)
