"""Request and response bodies of /api/v1/research-batches (ADR 0042, step BR4).

Input bodies accept only the documented fields. The organisation, the person who starts a batch, the
cap and every state come from the server; the client only chooses accounts and confirms the cost
figure it was shown.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BatchSelectionIn(BaseModel):
    """Which accounts: a saved filter, or ticked rows. The server resolves either one under the
    person's own read rules, so an id the person may not read is simply not in the batch."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["filter", "rows"]
    saved_filter_id: uuid.UUID | None = None
    # More than the cap is refused with a clear message by the service, not cut here.
    account_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    research_again: bool = False


class BatchStartIn(BatchSelectionIn):
    confirmed_upper_bound_tokens: int = Field(
        ge=0,
        le=100_000_000,
        description="The upper bound of tokens the estimate showed. The server recomputes it and "
        "refuses (409) if it moved by more than 20 %.",
    )


class RetryEstimateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    which: Literal["failed", "not_run", "both"] = "failed"


class RetryStartIn(RetryEstimateIn):
    confirmed_upper_bound_tokens: int = Field(ge=0, le=100_000_000)


class EstimateRead(BaseModel):
    accounts: int = Field(description="Accounts that would be in the batch.")
    not_available: int
    archived: int
    reused: int = Field(description="Accounts whose brief is under a day old: no cost.")
    calling_model: int
    upper_bound_tokens: int
    typical_tokens: int
    estimated_cost_usd: Decimal | None = Field(
        description="An estimate from the configured prices; null when no price is set."
    )
    cap_tokens: int
    monthly_tokens_left: int | None
    daily_left: int
    worst_case_tokens_per_account: int


class BatchRead(BaseModel):
    id: uuid.UUID
    status: Literal["running", "finished", "cancelled", "stopped_budget", "stopped_error"]
    source: Literal["filter", "rows"]
    saved_filter_id: uuid.UUID | None
    account_count: int
    not_available_count: int
    archived_count: int
    estimated_upper_tokens: int
    estimated_cost_usd: Decimal | None
    token_cap: int
    tokens_used: int
    research_again: bool
    cancel_requested: bool
    created_by_user_id: uuid.UUID
    mine: bool
    version: int
    created_at: datetime
    finished_at: datetime | None
    counts: dict[str, int] = Field(description="How many accounts are in each state.")


class BriefFiguresRead(BaseModel):
    """What the summary table shows about a brief. No sentence text, no record content."""

    brief_id: uuid.UUID
    created_at: datetime
    sentences: int
    dropped: int
    gathered: dict[str, int]
    tokens: int


class BatchItemRead(BaseModel):
    position: int
    account_id: uuid.UUID
    account_name: str | None = Field(description="Null when the person may not read the account.")
    status: Literal["queued", "running", "done", "reused", "skipped", "failed", "not_run"]
    failure_code: str | None
    brief_id: uuid.UUID | None
    input_tokens: int
    output_tokens: int
    brief: BriefFiguresRead | None
    model_config = ConfigDict(from_attributes=True)


class BatchDetailRead(BatchRead):
    items: list[BatchItemRead]


class BatchPage(BaseModel):
    items: list[BatchRead]
    total: int
    limit: int
    offset: int
