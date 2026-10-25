"""Request and response schemas for the leads API (these define the OpenAPI contract).

Request models use ``extra="forbid"``: a client that sends a field we don't accept - for
example ``tenant_id``, ``status`` or ``owner_id`` on an update - gets a 422 instead of having
it silently ignored. Server-controlled fields only ever appear in responses.
"""

import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

LeadStatus = Literal["new", "contacted", "qualified", "unqualified", "converted"]
LeadSource = Literal["web", "referral", "event", "cold_call", "partner", "advertisement", "other"]
UserActivityKind = Literal["note", "call", "email", "meeting"]
LeadSort = Literal[
    "-created_at", "created_at", "-updated_at", "updated_at", "last_name", "-last_name",
    "company_name", "-company_name", "-score", "score",
]  # fmt: skip
LeadPriority = Literal["hot", "warm", "cold"]
PropertyType = Literal["apartment", "villa", "plot", "commercial"]

_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]+$")
_PHONE = re.compile(r"^[0-9+().\-\s]{3,50}$")


def _email(value: str) -> str:
    if not _EMAIL.fullmatch(value):
        raise ValueError("must be a valid e-mail address")
    local, domain = value.rsplit("@", 1)
    return f"{local}@{domain.lower()}"


def _phone(value: str) -> str:
    if not _PHONE.fullmatch(value):
        raise ValueError("may contain only digits, spaces and + ( ) . -")
    return value


def _trimmed(max_length: int) -> StringConstraints:
    return StringConstraints(strip_whitespace=True, min_length=1, max_length=max_length)


Text100 = Annotated[str, _trimmed(100)]
Text150 = Annotated[str, _trimmed(150)]
Text200 = Annotated[str, _trimmed(200)]
Text255 = Annotated[str, _trimmed(255)]
Reason = Annotated[str, _trimmed(500)]
Email = Annotated[str, _trimmed(320), AfterValidator(_email)]
Phone = Annotated[str, _trimmed(50), AfterValidator(_phone)]
Text160 = Annotated[str, _trimmed(160)]
# Whole rupees. The upper limit (1 lakh crore) only catches typos such as extra zeros.
BudgetInr = Annotated[int, Field(ge=0, le=1_000_000_000_000)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LeadCreate(_Input):
    first_name: Text100 | None = None
    last_name: Text100
    company_name: Text255 | None = None
    email: Email | None = None
    phone: Phone | None = None
    job_title: Text150 | None = None
    source: LeadSource | None = None
    property_type: PropertyType | None = None
    budget_min_inr: BudgetInr | None = Field(default=None, description="Whole rupees.")
    budget_max_inr: BudgetInr | None = Field(default=None, description="Whole rupees.")
    location: Text160 | None = Field(default=None, description="Area or city they want.")
    owner_id: uuid.UUID | None = Field(
        default=None,
        description="Sales employee who should own the lead. Requires `lead:assign` unless it is "
        "you. Defaults to you if you have a sales role.",
    )

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "first_name": "Jamie",
                    "last_name": "Example",
                    "company_name": "Example Industries",
                    "email": "jamie@example.test",
                    "source": "web",
                }
            ]
        },
    )

    @model_validator(mode="after")
    def _budget_in_order(self) -> "LeadCreate":
        budget_in_order(self.budget_min_inr, self.budget_max_inr)
        return self


def budget_in_order(minimum: int | None, maximum: int | None) -> None:
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError("the minimum budget can't be above the maximum budget")


class LeadUpdate(_Input):
    """Partial update. Send only the fields to change, plus the ``version`` you last read."""

    version: int = Field(ge=1, description="Optimistic-lock version from your last read.")
    first_name: Text100 | None = None
    last_name: Text100 | None = None
    company_name: Text255 | None = None
    email: Email | None = None
    phone: Phone | None = None
    job_title: Text150 | None = None
    source: LeadSource | None = None
    property_type: PropertyType | None = None
    budget_min_inr: BudgetInr | None = None
    budget_max_inr: BudgetInr | None = None
    location: Text160 | None = None

    @model_validator(mode="after")
    def _check(self) -> "LeadUpdate":
        if not self.model_fields_set - {"version"}:
            raise ValueError("send at least one field to change")
        if "last_name" in self.model_fields_set and self.last_name is None:
            raise ValueError("last_name cannot be removed")
        return self

    def changes(self) -> dict[str, object]:
        return {k: getattr(self, k) for k in self.model_fields_set if k != "version"}


class LeadAssign(_Input):
    owner_id: uuid.UUID = Field(description="Active sales employee of your tenant.")
    reason: Reason | None = None


class LeadStatusChange(_Input):
    status: Literal["contacted", "qualified", "unqualified"] = Field(
        description="Target status. Use /convert to convert; allowed moves are documented in "
        "the module docs."
    )
    reason: Reason | None = None


class LeadQualify(_Input):
    reason: Reason | None = None


class LeadDisqualify(_Input):
    reason: Reason = Field(description="Why the lead is not a fit (required).")


class ConvertAccount(_Input):
    existing_account_id: uuid.UUID | None = Field(
        default=None, description="Link to an account you can already see instead of creating one."
    )
    name: Text255 | None = Field(
        default=None, description="Name for the new account. Defaults to the lead's company name."
    )

    @model_validator(mode="after")
    def _one_of(self) -> "ConvertAccount":
        if self.existing_account_id and self.name:
            raise ValueError("give either existing_account_id or name, not both")
        return self


class ConvertOpportunity(_Input):
    name: Text255 | None = Field(
        default=None, description="Defaults to '<company> - new opportunity'."
    )
    amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")] = Field(
        description="ISO 4217 code, e.g. EUR."
    )
    expected_close_date: date | None = None


class LeadConvert(_Input):
    account: ConvertAccount = Field(default_factory=ConvertAccount)
    opportunity: ConvertOpportunity | None = Field(
        default=None, description="Omit to convert without creating an opportunity."
    )


class ActivityCreate(_Input):
    kind: UserActivityKind
    subject: Text200
    body: Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)] | None = None
    occurred_at: datetime | None = Field(
        default=None, description="When it happened (with time zone). Defaults to now."
    )

    @model_validator(mode="after")
    def _aware(self) -> "ActivityCreate":
        if self.occurred_at is not None and self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must include a time zone, e.g. 2026-10-18T09:00:00Z")
        return self


# --- Responses --------------------------------------------------------------------------


class _Output(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LeadRead(_Output):
    id: uuid.UUID
    first_name: str | None
    last_name: str
    company_name: str | None
    email: str | None
    phone: str | None
    job_title: str | None
    status: LeadStatus
    source: str | None
    property_type: PropertyType | None = None
    budget_min_inr: int | None = None
    budget_max_inr: int | None = None
    location: str | None = None
    owner_id: uuid.UUID | None
    converted_at: datetime | None
    converted_account_id: uuid.UUID | None
    converted_contact_id: uuid.UUID | None
    converted_opportunity_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    version: int
    score: int | None = Field(default=None, description="Lead score 0-100 (see /score).")
    priority: LeadPriority | None = Field(
        default=None, description="hot (70+), warm (40-69) or cold (<40)."
    )


class ScoreFactor(BaseModel):
    label: str
    points: int


class LeadScore(BaseModel):
    lead_id: uuid.UUID
    score: int
    priority: LeadPriority
    factors: list[ScoreFactor]


class LeadPage(BaseModel):
    items: list[LeadRead]
    total: int = Field(description="Number of matching leads you may see (all pages).")
    limit: int
    offset: int


class ConversionResult(BaseModel):
    lead_id: uuid.UUID
    account_id: uuid.UUID
    contact_id: uuid.UUID
    opportunity_id: uuid.UUID | None
    converted_at: datetime
    already_converted: bool = Field(
        description="True if the lead had been converted before; nothing new was created."
    )


class ActivityRead(_Output):
    id: uuid.UUID
    lead_id: uuid.UUID
    kind: str
    subject: str
    body: str | None
    occurred_at: datetime
    actor_user_id: uuid.UUID | None


class AssignmentRead(_Output):
    id: uuid.UUID
    lead_id: uuid.UUID
    from_user_id: uuid.UUID | None
    to_user_id: uuid.UUID
    assigned_by_user_id: uuid.UUID | None
    reason: str | None
    assigned_at: datetime
