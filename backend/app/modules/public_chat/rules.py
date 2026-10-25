"""Rules of the public website chat that need no database (ADR 0013)."""

import hashlib
import hmac
import re
import secrets
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

# The model gets this many tool rounds per visitor message, then must answer in words.
MAX_TOOL_ROUNDS = 2
# How much of the conversation the model sees each time.
HISTORY_MESSAGES = 20
# What the visitor sees if the model ends without a usable answer.
FALLBACK_REPLY = (
    "Sorry, I couldn't answer that. Please leave your name and phone number and an advisor will "
    "call you."
)
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{40,100}$")

SYSTEM_PROMPT = """You are the property concierge on the website of {organisation}.
Help home buyers by collecting, in a friendly and brief way: their full name, phone number,
the property type (apartment, villa, plot or commercial), their budget, and the area they want.
Ask for missing details one or two at a time. Convert budgets to whole rupees
(1 crore = 10000000, 1 lakh = 100000). Never invent prices, projects or availability.
When the visitor has confirmed their name and phone number, call the save_lead tool once.
Afterwards thank them and say an advisor will call. You can't look anything up in the CRM.
Answer in plain text only - no links, no images, no Markdown."""

_PHONE = r"^\+?[0-9][0-9\s-]{6,18}[0-9]$"


class SaveLeadArgs(BaseModel):
    """What the model may send to save_lead. Anything else is refused (extra="forbid")."""

    model_config = ConfigDict(extra="forbid")

    full_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)
    ]
    phone: Annotated[str, StringConstraints(strip_whitespace=True, pattern=_PHONE)]
    email: (
        Annotated[
            str,
            StringConstraints(
                strip_whitespace=True, max_length=320, pattern=r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]+$"
            ),
        ]
        | None
    ) = None
    property_type: Literal["apartment", "villa", "plot", "commercial"] | None = None
    budget_min_inr: Annotated[int, Field(ge=0, le=1_000_000_000_000)] | None = None
    budget_max_inr: Annotated[int, Field(ge=0, le=1_000_000_000_000)] | None = None
    location: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
        | None
    ) = None
    notes: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
        | None
    ) = None

    @model_validator(mode="after")
    def _budget_in_order(self) -> "SaveLeadArgs":
        low, high = self.budget_min_inr, self.budget_max_inr
        if low is not None and high is not None and low > high:
            raise ValueError("budget_min_inr can't be above budget_max_inr")
        return self


def _tool_definition() -> dict[str, Any]:
    """The save_lead tool, built from SaveLeadArgs so the two can never drift apart."""
    schema = SaveLeadArgs.model_json_schema()
    return {
        "name": "save_lead",
        "description": (
            "Save the visitor's confirmed details as a lead for the sales team. Call it once, "
            "after the visitor confirmed at least their full name and phone number. Budgets are "
            "whole rupees."
        ),
        "input_schema": {
            "type": "object",
            "properties": schema["properties"],
            "required": ["full_name", "phone"],
            "additionalProperties": False,
        },
    }


SAVE_LEAD_TOOL = _tool_definition()


def split_name(full_name: str) -> tuple[str | None, str]:
    """ "Anil Kumar Reddy" -> ("Anil Kumar", "Reddy"); a single word is the last name."""
    parts = full_name.split()
    if len(parts) == 1:
        return None, parts[0]
    return " ".join(parts[:-1]), parts[-1]


def new_token() -> str:
    """A random conversation token (256 bits); only its hash is ever stored."""
    return secrets.token_urlsafe(32) + secrets.token_urlsafe(8)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_ip(address: str, server_key: str) -> str:
    """A keyed hash of the visitor's address: enough to count, impossible to read back."""
    return hmac.new(server_key.encode(), address.encode(), hashlib.sha256).hexdigest()
