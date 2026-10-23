"""Request and response shapes for contracts.

Numbers, statuses, termination data, the renewal reminder and the history are server-controlled:
a client sends the business facts of a contract only, and changes its status through the steps
(activate, terminate, renew).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.validation import Reason

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=10000)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
Money = Annotated[Decimal, Field(ge=0, max_digits=16, decimal_places=2)]
ContractStatus = Literal["draft", "active", "expired", "terminated", "renewed"]
BillingFrequency = Literal["one_time", "monthly", "quarterly", "annually"]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _dates_in_order(start: date | None, end: date | None) -> None:
    if start is not None and end is not None and end < start:
        raise ValueError("the end date cannot be before the start date")


class ContractCreate(_Input):
    account_id: uuid.UUID
    title: Title
    owner_id: uuid.UUID | None = Field(default=None, description="Default: you.")
    contact_id: uuid.UUID | None = Field(default=None, description="A contact of the same account.")
    opportunity_id: uuid.UUID | None = Field(
        default=None, description="A deal of the same account."
    )
    quote_id: uuid.UUID | None = Field(default=None, description="A quote of the same account.")
    start_date: date | None = None
    end_date: date | None = None
    auto_renew: bool = False
    renewal_notice_days: int = Field(default=30, ge=0, le=365)
    renewal_term_months: int | None = Field(default=None, ge=1, le=120)
    currency: Currency = "EUR"
    total_value: Money = Decimal("0")
    billing_frequency: BillingFrequency = "annually"
    terms: LongText | None = None

    @model_validator(mode="after")
    def _check(self) -> "ContractCreate":
        _dates_in_order(self.start_date, self.end_date)
        return self


class ContractUpdate(_Input):
    """Change a draft (any field below) or an active contract (owner, contact, title, auto-renew,
    notice, renewal term, terms)."""

    version: int = Field(ge=1)
    title: Title | None = None
    owner_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None
    start_date: date | None = None
    end_date: date | None = None
    auto_renew: bool | None = None
    renewal_notice_days: int | None = Field(default=None, ge=0, le=365)
    renewal_term_months: int | None = Field(default=None, ge=1, le=120)
    currency: Currency | None = None
    total_value: Money | None = None
    billing_frequency: BillingFrequency | None = None
    terms: LongText | None = None

    @model_validator(mode="after")
    def _check(self) -> "ContractUpdate":
        if not self.model_fields_set - {"version"}:
            raise ValueError("send at least one field to change")
        for required in (
            "title",
            "owner_id",
            "auto_renew",
            "renewal_notice_days",
            "currency",
            "total_value",
            "billing_frequency",
        ):
            if required in self.model_fields_set and getattr(self, required) is None:
                raise ValueError(f"{required} cannot be removed")
        _dates_in_order(self.start_date, self.end_date)
        return self


class Step(_Input):
    version: int = Field(ge=1, description="The version you are looking at (detects lost updates).")
    note: Note | None = None


class TerminateStep(_Input):
    version: int = Field(ge=1)
    reason: Reason = Field(min_length=1, description="Why the contract ends early (required).")


class RenewInput(_Input):
    """Create the renewal as a new draft. Dates and value default from the old contract."""

    version: int = Field(ge=1)
    start_date: date | None = None
    end_date: date | None = None
    total_value: Money | None = None
    note: Note | None = None

    @model_validator(mode="after")
    def _check(self) -> "RenewInput":
        _dates_in_order(self.start_date, self.end_date)
        return self


class NoteInput(_Input):
    note: Note


class _Read(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: int
    label: str
    title: str
    status: ContractStatus
    account_id: uuid.UUID
    account_name: str | None = None
    contact_id: uuid.UUID | None
    owner_id: uuid.UUID
    owner_name: str | None = None
    start_date: date | None
    end_date: date | None
    renewal_date: date | None = Field(description="From this day the owner is reminded.")
    days_to_end: int | None = Field(description="Negative once the end date has passed.")
    auto_renew: bool
    renewal_notice_days: int
    renewal_term_months: int | None
    currency: str
    total_value: Decimal
    billing_frequency: BillingFrequency
    renewed_from_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    version: int


class ContractSummary(_Read):
    pass


class ContractRead(_Read):
    opportunity_id: uuid.UUID | None
    quote_id: uuid.UUID | None
    terms: str | None
    terminated_at: datetime | None
    termination_reason: str | None
    renewal_reminded_at: datetime | None
    renewed_to_id: uuid.UUID | None = Field(
        default=None, description="The renewal that follows this contract, if one exists."
    )


class ContractPage(BaseModel):
    items: list[ContractSummary]
    total: int
    limit: int
    offset: int


class ContractEventRead(BaseModel):
    event_type: str
    from_status: str | None
    to_status: str | None
    note: str | None
    created_at: datetime
    actor_name: str | None
