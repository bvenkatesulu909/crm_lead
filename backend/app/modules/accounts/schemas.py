"""API request and response shapes for accounts.

Request models use ``extra="forbid"``: a client sending a field we don't accept (``tenant_id``,
``status``, ``deleted_at``...) gets a 422 instead of having it silently ignored. Status and
archiving only change through their own endpoints, which apply the business rules.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.validation import Phone, Reason, Text50, Text100, Text255, WebUrl

AccountStatus = Literal["active", "inactive"]
Segment = Literal["enterprise", "mid_market", "small_business", "public_sector", "non_profit"]
Channel = Literal["email", "phone", "mobile", "post", "none"]
Lifecycle = Literal["prospect", "onboarding", "active_customer", "at_risk", "churned"]
AccountType = Literal["company", "headquarters", "subsidiary", "branch"]
Country = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]
Language = Annotated[str, StringConstraints(pattern=r"^[a-z]{2}$")]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AccountCreate(_Input):
    name: Text255
    account_number: Text50 | None = Field(
        default=None, description="Optional external/ERP number, unique in your organisation."
    )
    website: WebUrl | None = None
    industry: Text100 | None = None
    phone: Phone | None = None
    segment: Segment | None = None
    preferred_channel: Channel | None = None
    country: Country | None = Field(default=None, description="ISO country code, e.g. DE.")
    region: Text100 | None = None
    city: Text100 | None = None
    lifecycle_stage: Lifecycle | None = None
    preferred_language: Language | None = Field(default=None, description="ISO 639-1, e.g. en.")
    account_type: AccountType = "company"
    parent_account_id: uuid.UUID | None = Field(
        default=None, description="Parent company. Must be an account you can see."
    )
    owner_id: uuid.UUID | None = Field(
        default=None,
        description="Sales employee who owns the account. Choosing someone else requires "
        "`account:write:all`. Defaults to you if you have a sales role.",
    )


class AccountUpdate(_Input):
    """Partial update. Send only the fields to change, plus the ``version`` you last read.
    Send ``null`` to clear an optional field."""

    version: int = Field(ge=1, description="Optimistic-lock version from your last read.")
    name: Text255 | None = None
    account_number: Text50 | None = None
    website: WebUrl | None = None
    industry: Text100 | None = None
    phone: Phone | None = None
    segment: Segment | None = None
    preferred_channel: Channel | None = None
    country: Country | None = Field(default=None, description="ISO country code, e.g. DE.")
    region: Text100 | None = None
    city: Text100 | None = None
    lifecycle_stage: Lifecycle | None = None
    preferred_language: Language | None = Field(default=None, description="ISO 639-1, e.g. en.")
    account_type: AccountType | None = None
    parent_account_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = Field(
        default=None, description="New owner (requires `account:write:all`)."
    )

    @model_validator(mode="after")
    def _check(self) -> "AccountUpdate":
        if not self.model_fields_set - {"version"}:
            raise ValueError("send at least one field to change")
        for required in ("name", "account_type"):
            if required in self.model_fields_set and getattr(self, required) is None:
                raise ValueError(f"{required} cannot be removed")
        return self

    def changes(self) -> dict[str, object]:
        return {k: getattr(self, k) for k in self.model_fields_set if k != "version"}


class AccountStatusChange(_Input):
    version: int = Field(ge=1)
    status: AccountStatus
    reason: Reason | None = None


class AccountArchive(_Input):
    version: int = Field(ge=1)
    reason: Reason


class AccountRestore(_Input):
    version: int = Field(ge=1)


class AccountRead(BaseModel):
    """What staff users see."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    account_number: str | None
    website: str | None
    industry: str | None
    phone: str | None
    status: str
    segment: str | None
    preferred_channel: str | None
    country: str | None
    region: str | None
    city: str | None
    lifecycle_stage: str | None
    account_type: str
    preferred_language: str | None
    owner_id: uuid.UUID | None
    parent_account_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = Field(description="Set when the account is archived.")
    version: int


class AccountPage(BaseModel):
    items: list[AccountRead]
    total: int
    limit: int
    offset: int


class TimelineEntry(BaseModel):
    """One change in the account's history (from the audit log)."""

    at: datetime
    action: str = Field(description="e.g. account.created, account.updated, account.contact_added")
    title: str
    changes: dict[str, Any]
    actor_name: str | None


class PortalAccountRead(BaseModel):
    """What customer-portal users see: no owners, internal numbers or audit fields."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    website: str | None
    status: str


class DuplicateCandidate(BaseModel):
    id: uuid.UUID
    name: str
    city: str | None
    country: str | None
    reasons: list[str] = Field(description="Why it may be the same customer.")


class DuplicateCheck(BaseModel):
    """Possible matches you may see, plus how many more exist that you may not see (no
    names are revealed for those)."""

    candidates: list[DuplicateCandidate]
    hidden_matches: int
