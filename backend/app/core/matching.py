"""Normalising names, web domains and phone numbers for duplicate detection.

Each rule exists twice - in Python for the value someone is typing and as a SQL expression for
the stored rows - so both sides are compared in exactly the same form. Tests check that the two
agree.
"""

import re
from typing import Any

from sqlalchemy import ColumnElement, SQLColumnExpression, func

# A mapped text column (nullable or not), e.g. Account.name or Contact.email.
Column = SQLColumnExpression[Any]

# Legal-form words that don't make two companies different ("Example Ltd" = "Example Limited").
_LEGAL = (
    "ltd|limited|gmbh|inc|incorporated|llc|llp|plc|co|corp|corporation|company|sa|ag|bv|nv|"
    "srl|spa|pvt|private|pte|pty|oy|ab|as|kg|ug"
)
_PUNCT_SQL = "[^a-z0-9 ]"
_LEGAL_SQL = rf"\m({_LEGAL})\M"
_LEGAL_PY = re.compile(rf"\b({_LEGAL})\b")
_DOMAIN_SQL = r"^([a-z]+://)?(www\.)?([^/:?#]+).*$"
_DOMAIN_PY = re.compile(_DOMAIN_SQL)
PHONE_TAIL = 9  # compare the last 9 digits: ignores country prefixes like +44 / 0


def company_key(name: str) -> str:
    text = re.sub(_PUNCT_SQL, " ", name.lower())
    text = _LEGAL_PY.sub(" ", text)
    return " ".join(text.split())


def company_key_sql(column: Column) -> ColumnElement[str]:
    text = func.regexp_replace(func.lower(column), _PUNCT_SQL, " ", "g")
    text = func.regexp_replace(text, _LEGAL_SQL, " ", "g")
    return func.btrim(func.regexp_replace(text, r"\s+", " ", "g"))


def domain_key(website: str) -> str:
    match = _DOMAIN_PY.match(website.strip().lower())
    return match.group(3) if match else ""


def domain_key_sql(column: Column) -> ColumnElement[str]:
    return func.regexp_replace(func.lower(column), _DOMAIN_SQL, r"\3")


def phone_key(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    return digits[-PHONE_TAIL:] if len(digits) >= 7 else ""


def phone_key_sql(column: Column) -> ColumnElement[str]:
    return func.right(func.regexp_replace(column, r"\D", "", "g"), PHONE_TAIL)
