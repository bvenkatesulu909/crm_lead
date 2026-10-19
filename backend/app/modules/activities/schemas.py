"""Request and response shapes for activities and tasks."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.validation import Reason

Kind = Literal["task", "call", "meeting", "email", "note"]
Status = Literal["open", "done", "cancelled"]
Priority = Literal["low", "normal", "high"]
Subject = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Body = Annotated[str, StringConstraints(strip_whitespace=True, max_length=10_000)]
RELATED = ("lead_id", "account_id", "contact_id", "opportunity_id")
# Clocks differ a little between browser and server.
_CLOCK_SLACK = timedelta(minutes=5)


def _aware(value: datetime | None, name: str) -> None:
    if value is not None and value.tzinfo is None:
        raise ValueError(f"{name} must include a time zone, e.g. 2026-10-19T09:00:00Z")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActivityCreate(_Input):
    kind: Kind
    subject: Subject
    body: Body | None = None
    status: Literal["open", "done"] | None = Field(
        default=None,
        description="`open` = a task or planned follow-up; `done` = log something that "
        "already happened. Default: `done` for notes, `open` for everything else.",
    )
    priority: Priority = "normal"
    due_at: datetime | None = Field(default=None, description="When an open item is due.")
    reminder_at: datetime | None = Field(
        default=None, description="When to remind the assignee (open items only)."
    )
    occurred_at: datetime | None = Field(
        default=None, description="For `done` items: when it happened. Defaults to now."
    )
    outcome: Reason | None = None
    assignee_id: uuid.UUID | None = Field(
        default=None,
        description="Who does it. Defaults to you; others need `activity:assign`.",
    )
    lead_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _check(self) -> "ActivityCreate":
        for name in ("due_at", "reminder_at", "occurred_at"):
            _aware(getattr(self, name), name)
        if sum(getattr(self, r) is not None for r in RELATED) > 1:
            raise ValueError("link the activity to at most one record")
        if self.status is None:
            self.status = "done" if self.kind == "note" else "open"
        if self.kind == "note" and self.status != "done":
            raise ValueError("a note records something; it cannot be an open task")
        if self.status == "done":
            if self.due_at or self.reminder_at:
                raise ValueError("due and reminder dates are for open items")
            if self.occurred_at and self.occurred_at > datetime.now(UTC) + _CLOCK_SLACK:
                raise ValueError("a logged activity cannot be in the future")
        else:
            if self.occurred_at or self.outcome:
                raise ValueError("occurred_at and outcome are for logged (done) items")
            if self.reminder_at and self.due_at and self.reminder_at > self.due_at:
                raise ValueError("the reminder must be before the due date")
        return self


class ActivityUpdate(_Input):
    """Partial update of an OPEN activity. Send the fields to change plus ``version``."""

    version: int = Field(ge=1)
    subject: Subject | None = None
    body: Body | None = None
    priority: Priority | None = None
    due_at: datetime | None = None
    reminder_at: datetime | None = None
    assignee_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _check(self) -> "ActivityUpdate":
        if not self.model_fields_set - {"version"}:
            raise ValueError("send at least one field to change")
        for required in ("subject", "priority", "assignee_id"):
            if required in self.model_fields_set and getattr(self, required) is None:
                raise ValueError(f"{required} cannot be removed")
        _aware(self.due_at, "due_at")
        _aware(self.reminder_at, "reminder_at")
        return self

    def changes(self) -> dict[str, object]:
        return {k: getattr(self, k) for k in self.model_fields_set if k != "version"}


class Complete(_Input):
    version: int = Field(ge=1)
    outcome: Reason | None = None


class Cancel(_Input):
    version: int = Field(ge=1)
    reason: Reason | None = None


class Reopen(_Input):
    version: int = Field(ge=1)


class ActivityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    subject: str
    body: str | None
    status: str
    priority: str
    due_at: datetime | None
    reminder_at: datetime | None
    completed_at: datetime | None
    outcome: str | None
    overdue: bool = Field(description="Open and past its due time.")
    assignee_id: uuid.UUID
    created_by_user_id: uuid.UUID | None
    related_type: Literal["lead", "account", "contact", "opportunity"] | None
    related_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    version: int


class ActivityPage(BaseModel):
    items: list[ActivityRead]
    total: int
    limit: int
    offset: int


class Reminders(BaseModel):
    """What needs the signed-in user's attention now (their own open items)."""

    overdue: int
    due_next_24h: int
    reminders_due: int = Field(description="Open items whose reminder time has passed.")
    attention: int = Field(description="Distinct items in any of the three groups (for a badge).")
    items: list[ActivityRead] = Field(description="The most urgent items (max 10).")
