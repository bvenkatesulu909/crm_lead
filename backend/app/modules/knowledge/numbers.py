"""RERA numbers and rupee amounts in questions, sources and answers (CRM-115 / BP-08, step BR2).

Pure functions, no database and no model. They let the answer pipeline refuse an answer that quotes
a RERA number or a price its cited sources do not contain (docs/brochures-rera.md, section 3b).
A wrong registration number or price can cost a buyer real money, so "the model cited a document"
is not enough: the number itself must be in what it cited.
"""

import re
from collections.abc import Iterable, Sequence
from decimal import Decimal, InvalidOperation

# A RERA-shaped token: letters, digits and the separators registries use, with at least one
# letter and at least six digits. Covers e.g. P02400001234 (Telangana), P51800012345
# (Maharashtra), PRM/KA/RERA/1251/309/PR/171014/000526 (Karnataka) and the demo DEMO-P0240....
_TOKEN = re.compile(r"(?<![A-Za-z0-9/\-])[A-Za-z0-9][A-Za-z0-9/\-]{6,59}(?<![/\-])")
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_SEPARATORS = re.compile(r"[\s\-]")

# Rupee amounts: a currency sign and/or an Indian unit. A bare number is never an amount.
_UNITS = {"lakh": 5, "lakhs": 5, "lac": 5, "lacs": 5, "l": 5, "crore": 7, "crores": 7, "cr": 7}
_AMOUNT = re.compile(
    r"(?P<currency>₹|\bRs\.?|\bINR)?\s*"
    r"(?P<number>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?:\s*(?P<unit>lakhs?|lacs?|crores?|cr|l)\b)?",
    re.IGNORECASE,
)


def rera_numbers(text: str) -> list[str]:
    """RERA-shaped numbers in the order they appear (each once)."""
    found: list[str] = []
    for match in _TOKEN.finditer(text):
        token = match.group(0)
        if _UUID.fullmatch(token) or _DATE.fullmatch(token):
            continue
        if not any(c.isalpha() for c in token):
            continue
        if sum(c.isdigit() for c in token) < 6:
            continue
        if token not in found:
            found.append(token)
    return found


def normalise(number: str) -> str:
    """Upper case without spaces and dashes; slashes are part of some registries' numbers."""
    return _SEPARATORS.sub("", number).upper()


def contains_number(text: str, number: str) -> bool:
    """Whether ``text`` holds exactly this number (not a longer or a shorter one)."""
    wanted = normalise(number)
    return any(normalise(token) == wanted for token in rera_numbers(text))


def mentions_rera(text: str) -> bool:
    return bool(rera_numbers(text))


def rupee_amounts(text: str) -> set[int]:
    """Amounts in whole rupees: "₹85 lakh", "1.2 Cr", "Rs 1,20,00,000", "INR 80 L" ..."""
    amounts: set[int] = set()
    for match in _AMOUNT.finditer(text):
        currency, unit = match.group("currency"), match.group("unit")
        if not currency and not unit:
            continue  # a bare number (an area, a year, a phone number) is not a price
        try:
            value = Decimal(match.group("number").replace(",", ""))
        except InvalidOperation:
            continue
        if unit:
            value *= Decimal(10) ** _UNITS[unit.lower()]
        amounts.add(int(value))
    return amounts


def unsupported(answer: str, cited_texts: Sequence[str], *, question: str) -> str | None:
    """Why this answer may not be shown, or None.

    ``rera_not_cited``: a RERA number in the answer is in none of the CITED sources.
    ``price_not_cited``: an amount is in none of the cited sources and not in the question (the
    person's own budget may be repeated back to them)."""
    for number in rera_numbers(answer):
        if not any(contains_number(text, number) for text in cited_texts):
            return "rera_not_cited"
    allowed = _union(rupee_amounts(text) for text in [*cited_texts, question])
    if rupee_amounts(answer) - allowed:
        return "price_not_cited"
    return None


def _union(sets: Iterable[set[int]]) -> set[int]:
    result: set[int] = set()
    for item in sets:
        result |= item
    return result
