"""Pure helpers for the proposal deck (ADR 0032, PD2): money, number and date words, line paging and
the "can the font draw this?" filter. No database, no drawing."""

from collections.abc import Mapping, Sequence
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


# --- scripts (ADR 0032 Amendment A, PD5) ----------------------------------------------------
# Each run of text is drawn with the bundled font of its script. Everything that is not
# Devanagari or Telugu (letters, digits, punctuation, the rupee sign) uses the Latin Noto Sans.

LATIN, DEVANAGARI, TELUGU = "latin", "devanagari", "telugu"
SCRIPTS = (LATIN, DEVANAGARI, TELUGU)
_JOINERS = ("\u200c", "\u200d")  # zero-width non-joiner / joiner: they belong to their neighbours


def script_of(ch: str) -> str:
    """The font family a character is drawn with: devanagari, telugu or latin (everything else)."""
    code = ord(ch)
    if 0x0900 <= code <= 0x097F or 0xA8E0 <= code <= 0xA8FF:
        return DEVANAGARI
    if 0x0C00 <= code <= 0x0C7F:
        return TELUGU
    return LATIN


def script_runs(text: str) -> list[tuple[str, str]]:
    """Split ``text`` into runs of one script each, in order. A joiner stays with the run before it
    (it only has a meaning between two letters of the same script)."""
    runs: list[tuple[str, str]] = []
    for ch in text:
        script = runs[-1][0] if ch in _JOINERS and runs else script_of(ch)
        if runs and runs[-1][0] == script:
            runs[-1] = (script, runs[-1][1] + ch)
        else:
            runs.append((script, ch))
    return runs


def printable_scripts(text: str, can_draw: Mapping[str, "set[int] | frozenset[int]"]) -> str:
    """Like ``printable`` but each character is checked against the font of its own script, so Hindi
    and Telugu stay and anything no bundled font has (Chinese, emoji) becomes ``?``."""
    out: list[str] = []
    script = LATIN
    for ch in text:
        if ch in ("\n", " "):
            out.append(ch)
            continue
        script = script if ch in _JOINERS else script_of(ch)
        out.append(ch if ord(ch) in can_draw[script] else UNKNOWN)
    return "".join(out)
