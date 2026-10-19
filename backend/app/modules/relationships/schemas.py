"""Request and response shapes for ownership transfer and customer health."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.core.validation import Reason


class Transfer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1, description="Account version from your last read.")
    new_owner_id: uuid.UUID = Field(description="Active sales employee of your organisation.")
    reason: Reason
    include_contacts: bool = Field(
        default=True, description="Also move the account's contacts owned by the previous owner."
    )
    include_open_opportunities: bool = Field(
        default=True, description="Also move the previous owner's OPEN deals on this account."
    )
    include_open_tasks: bool = Field(
        default=True,
        description="Also reassign the previous owner's open tasks on the account, its contacts "
        "and its deals.",
    )


class TransferResult(BaseModel):
    account_id: uuid.UUID
    previous_owner_id: uuid.UUID | None
    new_owner_id: uuid.UUID
    version: int
    contacts_moved: int
    opportunities_moved: int
    tasks_moved: int


class FactorRead(BaseModel):
    label: str
    impact: int


class MoneyRead(BaseModel):
    currency: str
    amount: Decimal


class HealthRead(BaseModel):
    account_id: uuid.UUID
    score: int = Field(description="0-100; built only from the factors listed.")
    label: str = Field(description="healthy (75+), watch (50-74) or at_risk (<50).")
    last_interaction_at: datetime | None
    days_inactive: int | None
    inactive: bool = Field(description="No interaction for 90 days or more (or never).")
    factors: list[FactorRead]
    lifetime_value: list[MoneyRead] = Field(description="Issued invoices, per currency.")


class HealthRow(BaseModel):
    account_id: uuid.UUID
    name: str
    owner_id: uuid.UUID | None
    lifecycle_stage: str | None
    score: int
    label: str
    days_inactive: int | None
    inactive: bool
    top_factor: str | None


class HealthOverview(BaseModel):
    """Accounts you may see, least healthy first (up to `limit` accounts are assessed)."""

    assessed: int
    at_risk: int
    watch: int
    healthy: int
    inactive: int
    items: list[HealthRow]
