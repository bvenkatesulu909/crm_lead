"""Pure rules of saved filters (ADR 0042, step BR-pre): what a saved filter may hold.

A saved filter is only a **name plus the Accounts list's own filter parameters**. It never holds
SQL, paging or the archived switch, and every value is checked against the same vocabulary the list
endpoint accepts. Applying a saved filter is therefore exactly the same as typing those filters on
the list: the person's read rules still decide what comes back.
"""

import re
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

RECORD_TYPES = ("account",)
NAME_MAX = 80
MAX_PER_PERSON = 50
MAX_SHARED = 50
MAX_PARAMS = 10

STATUSES = ("active", "inactive")
SEGMENTS = ("enterprise", "mid_market", "small_business", "public_sector", "non_profit")
LIFECYCLES = ("prospect", "onboarding", "active_customer", "at_risk", "churned")
ACCOUNT_TYPES = ("company", "headquarters", "subsidiary", "branch")

_CURRENCY = re.compile(r"^[A-Z]{3}$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")
# Control and hidden characters have no place in a name or a search text.
_BAD_CHARS = re.compile("[\x00-\x1f\x7f​-‏‪-‮⁠-⁤﻿]")


class InvalidFilterError(ValueError):
    """A name or a parameter that a saved filter may not hold; the message is safe to show."""


def clean_name(raw: str) -> str:
    name = " ".join(raw.split())
    if not name:
        raise InvalidFilterError("Give the filter a name.")
    if len(name) > NAME_MAX or _BAD_CHARS.search(raw):
        raise InvalidFilterError(f"A name has at most {NAME_MAX} characters and no hidden ones.")
    if re.search(r"https?://|www\.|<|>", name, re.IGNORECASE):
        raise InvalidFilterError("A name cannot hold a link or markup.")
    return name


def _text(key: str, value: Any, limit: int) -> str:
    if not isinstance(value, str):
        raise InvalidFilterError(f"{key} must be text.")
    text = " ".join(value.split())
    if not text or len(text) > limit or _BAD_CHARS.search(value):
        raise InvalidFilterError(f"{key} must be 1 to {limit} visible characters.")
    return text


def _choice(key: str, value: Any, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise InvalidFilterError(f"{key} must be one of: {', '.join(allowed)}.")
    return str(value)


def _uuid(key: str, value: Any) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        raise InvalidFilterError(f"{key} must be an id.") from None


def _money(key: str, value: Any) -> str:
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise InvalidFilterError(f"{key} must be a number.") from None
    if not amount.is_finite() or amount < 0 or amount > Decimal("1e15"):
        raise InvalidFilterError(f"{key} must be between 0 and 1e15.")
    return format(amount.normalize(), "f")


def _pattern(key: str, value: Any, regex: re.Pattern[str]) -> str:
    if not isinstance(value, str) or not regex.match(value):
        raise InvalidFilterError(f"{key} has the wrong format.")
    return value


# The same names and limits as the list endpoint's query parameters. `archived`, `limit` and
# `offset` are deliberately missing: a saved filter never widens or pages a list.
def clean_account_params(params: dict[str, Any]) -> dict[str, str]:
    if len(params) > MAX_PARAMS:
        raise InvalidFilterError("Too many filter parameters.")
    cleaned: dict[str, str] = {}
    for key, value in params.items():
        if key == "q":
            cleaned[key] = _text(key, value, 100)
        elif key == "status":
            cleaned[key] = _choice(key, value, STATUSES)
        elif key == "segment":
            cleaned[key] = _choice(key, value, SEGMENTS)
        elif key == "lifecycle_stage":
            cleaned[key] = _choice(key, value, LIFECYCLES)
        elif key == "account_type":
            cleaned[key] = _choice(key, value, ACCOUNT_TYPES)
        elif key == "industry":
            cleaned[key] = _text(key, value, 100)
        elif key == "country":
            cleaned[key] = _pattern(key, value, _COUNTRY)
        elif key == "owner_id":
            cleaned[key] = _uuid(key, value)
        elif key == "min_value":
            cleaned[key] = _money(key, value)
        elif key == "value_currency":
            cleaned[key] = _pattern(key, value, _CURRENCY)
        else:
            raise InvalidFilterError(f"'{key}' cannot be part of a saved filter.")
    if ("min_value" in cleaned) != ("value_currency" in cleaned):
        raise InvalidFilterError("min_value and value_currency go together.")
    if not cleaned:
        raise InvalidFilterError("A saved filter needs at least one condition.")
    return cleaned


def clean_params(record_type: str, params: dict[str, Any]) -> dict[str, str]:
    if record_type not in RECORD_TYPES:
        raise InvalidFilterError("Filters can be saved for accounts only.")
    return clean_account_params(params)


@dataclass(frozen=True)
class Visibility:
    """Who sees a filter: its owner, or everyone in the organisation when it is shared."""

    owner_id: uuid.UUID
    shared: bool

    def visible_to(self, user_id: uuid.UUID) -> bool:
        return self.shared or self.owner_id == user_id
