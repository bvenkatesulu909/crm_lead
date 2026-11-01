"""Request and response bodies of /api/v1/qualifier (docs/qualifier.md).

The tenant, the version number and who saved never come from the client: the save body lists
the name, the steps and the version the person was looking at, nothing else is accepted.
"""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

# Wide bounds here; the service applies the exact rules after cleaning (and says which step).
Step = Annotated[str, Field(max_length=2000)]


class ProcedureSave(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=300)]
    steps: Annotated[list[Step], Field(min_length=1, max_length=40)]
    # The active version the person edited; omit it when there is none yet.
    replaces_version: Annotated[int | None, Field(ge=1)] = None


class ProcedureDeactivate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Annotated[int, Field(ge=1)]


class ProcedureRead(BaseModel):
    id: uuid.UUID
    version: int
    name: str
    steps: list[str]
    # Kinds of text taken out when it was saved (links, addresses, markup, hidden characters).
    cleaned: list[str]
    active: bool
    retired_at: datetime | None
    created_by_user_id: uuid.UUID
    created_at: datetime


class ProcedurePage(BaseModel):
    items: list[ProcedureRead]
    total: int
    limit: int
    offset: int


class AssessmentCreate(BaseModel):
    """Ask for an assessment of one lead. The person and the organisation come from the token."""

    model_config = ConfigDict(extra="forbid")

    lead_id: uuid.UUID


class AssessmentRead(BaseModel):
    id: uuid.UUID
    lead_id: uuid.UUID
    procedure_version: int
    decision: str
    matched_steps: list[int]
    reasons: list[str]
    missing: list[str]
    outcome: str
    proposal_id: uuid.UUID | None
    # Where the person who approves sees the proposal; None when nothing was proposed.
    proposal_link: str | None
    requested_by_user_id: uuid.UUID
    created_at: datetime
    # Only on the answer to "assess": why the safety check refused the proposal, if it did.
    blocked_message: str | None = None


class AssessmentPage(BaseModel):
    items: list[AssessmentRead]
    total: int
    limit: int
    offset: int


class TryRequest(BaseModel):
    """A dry run for an administrator: assess one lead with the active steps, or with a draft."""

    model_config = ConfigDict(extra="forbid")

    lead_id: uuid.UUID
    steps: Annotated[list[Step], Field(min_length=1, max_length=40)] | None = None


class TryRead(BaseModel):
    decision: str
    matched_steps: list[int]
    reasons: list[str]
    missing: list[str]
    # What would be put in front of an approver, in words; None when nothing would be proposed.
    would_propose: str | None
    # The saved version used; None for a draft.
    procedure_version: int | None
