"""API request and response shapes for contacts.

``email_consent_at`` is server-controlled: the server stamps it whenever the consent answer
changes, so a client can't back-date consent.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.validation import Email, Phone, Reason, Text100, Text150

Channel = Literal["email", "phone", "mobile", "post", "none"]
EmailConsent = Literal["unknown", "granted", "withdrawn"]
Language = Annotated[str, StringConstraints(pattern=r"^[a-z]{2}$")]
ContactSort = Literal[
    "last_name", "-last_name", "created_at", "-created_at", "updated_at", "-updated_at"
]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Details(_Input):
    first_name: Text100 | None = None
    email: Email | None = None
    phone: Phone | None = None
    mobile: Phone | None = None
    job_title: Text150 | None = Field(default=None, description="Designation, e.g. Head of IT.")
    department: Text100 | None = None
    account_id: uuid.UUID | None = Field(
        default=None, description="The customer account this person works for (one you can see)."
    )
    is_primary: bool | None = Field(
        default=None,
        description="Main contact of the account. Setting it removes the flag from the account's "
        "previous primary contact.",
    )
    preferred_channel: Channel | None = None
    email_consent: EmailConsent | None = Field(
        default=None, description="Marketing e-mail consent; the server records when it changed."
    )
    do_not_call: bool | None = None
    preferred_language: Language | None = Field(default=None, description="ISO 639-1, e.g. en.")


class ContactCreate(_Details):
    last_name: Text100
    owner_id: uuid.UUID | None = Field(
        default=None,
        description="Sales employee responsible. Choosing someone else requires "
        "`contact:write:all`. Defaults to you if you have a sales role.",
    )


class ContactUpdate(_Details):
    """Partial update. Send only the fields to change, plus the ``version`` you last read.
    Send ``null`` to clear an optional field."""

    version: int = Field(ge=1, description="Optimistic-lock version from your last read.")
    last_name: Text100 | None = None
    owner_id: uuid.UUID | None = Field(
        default=None, description="New owner (requires `contact:write:all`)."
    )

    @model_validator(mode="after")
    def _check(self) -> "ContactUpdate":
        if not self.model_fields_set - {"version"}:
            raise ValueError("send at least one field to change")
        for required in ("last_name", "is_primary", "email_consent", "do_not_call"):
            if required in self.model_fields_set and getattr(self, required) is None:
                raise ValueError(f"{required} cannot be removed")
        return self

    def changes(self) -> dict[str, object]:
        return {k: getattr(self, k) for k in self.model_fields_set if k != "version"}


class ContactArchive(_Input):
    version: int = Field(ge=1)
    reason: Reason | None = None


class ContactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    first_name: str | None
    last_name: str
    email: str | None
    phone: str | None
    mobile: str | None
    job_title: str | None
    department: str | None
    account_id: uuid.UUID | None
    owner_id: uuid.UUID | None
    is_primary: bool
    preferred_channel: str | None
    email_consent: str
    email_consent_at: datetime | None
    do_not_call: bool
    preferred_language: str | None
    created_at: datetime
    updated_at: datetime
    version: int


class ContactPage(BaseModel):
    items: list[ContactRead]
    total: int = Field(description="Number of matching contacts you may see (all pages).")
    limit: int
    offset: int


class HistoryEntry(BaseModel):
    at: datetime
    action: str
    title: str
    changes: dict[str, Any]
    actor_name: str | None


class ContactDuplicate(BaseModel):
    id: uuid.UUID
    name: str
    email: str | None
    account_id: uuid.UUID | None
    reasons: list[str]


class ContactDuplicateCheck(BaseModel):
    candidates: list[ContactDuplicate]
    hidden_matches: int = Field(description="Matches you may not see (no details given).")
