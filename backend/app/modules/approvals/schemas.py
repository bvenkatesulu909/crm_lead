"""Requests and responses of the approval queue (ADR 0014).

Proposals are never created through the API: only AI features inside the CRM propose (through
the service). People only read and decide - with just a version and a note.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

Status = Literal["pending", "approved", "rejected", "expired", "failed"]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class SafetyWarning(BaseModel):
    """Something the approver should check (the Sentinel, ADR 0017). Shown as "Safety check"."""

    code: str
    message: str


class PlannedChange(BaseModel):
    """One field the proposal will change (ADR 0018): ids and codes only, never names."""

    field: str
    before: Any
    after: Any


class SeenValue(BaseModel):
    field: str
    after: Any


class ActionOutcome(BaseModel):
    """What happened when the proposal was approved, next to what was announced."""

    ran: bool
    # None: not judged (a proposal made before plans existed, or an action that did not run).
    matches_plan: bool | None
    differs: list[str]
    seen: list[SeenValue]


class AgentActionRead(BaseModel):
    id: uuid.UUID
    kind: str
    description: str
    target_type: str
    target_id: uuid.UUID
    target_link: str
    # The record's name, only if the reader may see that record.
    target_label: str | None
    payload: dict[str, Any]
    reason: str
    agent: str
    requested_by_user_id: uuid.UUID
    status: Status
    expires_at: datetime
    decided_by_user_id: uuid.UUID | None
    decided_at: datetime | None
    decision_note: str | None
    result: str | None
    warnings: list[SafetyWarning]
    changes: list[PlannedChange]
    outcome: ActionOutcome | None
    created_at: datetime
    version: int


class AgentActionPage(BaseModel):
    items: list[AgentActionRead]
    total: int
    limit: int
    offset: int


class Approve(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    note: Note | None = None


class Reject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
