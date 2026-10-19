"""Request and response shapes for opportunities.

Stage, close date and lost reason only change through their own endpoints (move, won, lost,
reopen), which apply the pipeline rules. Probability and weighted value are calculated by the
server from the stage.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.validation import Reason, Text255

Stage = Literal[
    "prospecting", "qualification", "proposal", "negotiation", "closed_won", "closed_lost"
]
OpenStage = Literal["prospecting", "qualification", "proposal", "negotiation"]
Amount = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=2)]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OpportunityCreate(_Input):
    name: Text255
    account_id: uuid.UUID = Field(description="The customer account (one you can see).")
    primary_contact_id: uuid.UUID | None = Field(
        default=None, description="A contact of the same account."
    )
    owner_id: uuid.UUID | None = Field(
        default=None,
        description="Deal owner. Choosing someone else requires `opportunity:write:all`. "
        "Defaults to you if you have a sales role.",
    )
    stage: OpenStage = "prospecting"
    amount: Amount | None = Field(default=None, description="Estimated value (decimal).")
    currency: Currency = "EUR"
    expected_close_date: date | None = None
    next_step: Reason | None = None
    description: LongText | None = None


class OpportunityUpdate(_Input):
    """Partial update of an OPEN opportunity. Send the fields to change plus ``version``."""

    version: int = Field(ge=1)
    name: Text255 | None = None
    primary_contact_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    amount: Amount | None = None
    currency: Currency | None = None
    expected_close_date: date | None = None
    next_step: Reason | None = None
    description: LongText | None = None

    @model_validator(mode="after")
    def _check(self) -> "OpportunityUpdate":
        if not self.model_fields_set - {"version"}:
            raise ValueError("send at least one field to change")
        for required in ("name", "currency"):
            if required in self.model_fields_set and getattr(self, required) is None:
                raise ValueError(f"{required} cannot be removed")
        return self

    def changes(self) -> dict[str, object]:
        return {k: getattr(self, k) for k in self.model_fields_set if k != "version"}


class StageMove(_Input):
    version: int = Field(ge=1)
    stage: OpenStage
    note: Reason | None = None


class MarkWon(_Input):
    version: int = Field(ge=1)
    note: Reason | None = None


class MarkLost(_Input):
    version: int = Field(ge=1)
    reason: Reason


class Reopen(_Input):
    version: int = Field(ge=1)
    stage: OpenStage = "negotiation"
    note: Reason | None = None


class OpportunityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    account_id: uuid.UUID
    primary_contact_id: uuid.UUID | None
    owner_id: uuid.UUID | None
    stage: str
    probability: int = Field(description="Chance of winning in % (from the stage).")
    amount: Decimal | None = Field(description="Decimal string; never a float.")
    weighted_amount: Decimal | None = Field(description="amount × probability.")
    currency: str
    expected_close_date: date | None
    closed_at: datetime | None
    lost_reason: str | None
    next_step: str | None
    description: str | None
    created_at: datetime
    updated_at: datetime
    version: int


class OpportunityPage(BaseModel):
    items: list[OpportunityRead]
    total: int = Field(description="Number of matching opportunities you may see (all pages).")
    limit: int
    offset: int


class MoneyRead(BaseModel):
    currency: str
    amount: Decimal


class BoardColumn(BaseModel):
    stage: str
    probability: int
    count: int
    value: list[MoneyRead]
    weighted: list[MoneyRead]
    items: list[OpportunityRead] = Field(description="Up to `limit` cards, closing soonest first.")


class Board(BaseModel):
    columns: list[BoardColumn] = Field(description="The four open stages, in pipeline order.")
    won: BoardColumn
    lost: BoardColumn


class StageChangeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_stage: str | None
    to_stage: str
    note: str | None
    changed_at: datetime
    changed_by_name: str | None = None
