"""Request and answer shapes of /api/v1/deal-desk (ADR 0024, step DD3)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ReviewCreate(BaseModel):
    """Ask the deal desk to review one deal. The person and the organisation come from the token;
    nothing else is accepted."""

    model_config = ConfigDict(extra="forbid")

    opportunity_id: uuid.UUID


class CitedRecord(BaseModel):
    type: Literal["opportunity", "quote", "account", "contract"]
    id: uuid.UUID


class FindingRead(BaseModel):
    reviewer: Literal["pricing", "account", "momentum"]
    severity: Literal["info", "watch", "act"]
    # Written by a model and cleaned (no links, pictures or hidden text): show it as plain text.
    text: str
    records: list[CitedRecord]


class ProposalRef(BaseModel):
    id: uuid.UUID
    link: str


class ReviewRead(BaseModel):
    id: uuid.UUID
    opportunity_id: uuid.UUID
    created_at: datetime
    # Written by a model and cleaned: show it as plain text.
    brief: str
    findings: list[FindingRead]
    # "answered" or "refused" per reviewer.
    reviewers: dict[str, Literal["answered", "refused"]]
    proposals: list[ProposalRef]


class ReviewCreated(ReviewRead):
    # Why the safety check refused a suggested task, if it did (plain words, no model text).
    blocked_messages: list[str]


class ReviewList(BaseModel):
    items: list[ReviewRead]
