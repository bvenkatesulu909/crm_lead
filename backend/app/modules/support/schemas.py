"""Request/response contracts for tickets. Staff and customers get DIFFERENT response models:
customers never receive assignees, SLA data, channels or internal comments."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

TicketStatus = Literal["new", "open", "pending_customer", "resolved", "closed"]
TicketPriority = Literal["low", "normal", "high", "urgent"]
TicketChannel = Literal["portal", "staff", "assistant"]
SlaStateName = Literal["on_track", "at_risk", "breached", "met"]
TicketSort = Literal["-created_at", "created_at", "-updated_at", "resolution_due_at"]

Subject = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10_000)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


TicketCategory = Literal["question", "problem", "request", "complaint", "feedback"]


class TicketCreate(_Input):
    """Staff create a ticket on behalf of a customer account."""

    account_id: uuid.UUID
    subject: Subject
    description: LongText
    priority: TicketPriority = "normal"
    category: TicketCategory = "question"


class PortalTicketCreate(_Input):
    """A customer opens a ticket for one of their own accounts."""

    account_id: uuid.UUID = Field(description="Must be one of the accounts you can see.")
    subject: Subject
    description: LongText
    category: TicketCategory = "question"


class TicketUpdate(_Input):
    """Change priority (recalculates SLA deadlines) and/or category."""

    version: int = Field(ge=1)
    priority: TicketPriority | None = None
    category: TicketCategory | None = None

    @model_validator(mode="after")
    def _check(self) -> "TicketUpdate":
        if self.priority is None and self.category is None:
            raise ValueError("send priority and/or category")
        return self


class TicketRating(_Input):
    """The customer's satisfaction with how a resolved ticket was handled."""

    rating: int = Field(ge=1, le=5, description="1 = very unhappy ... 5 = very happy")
    comment: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None


class TicketStatusChange(_Input):
    status: Literal["open", "pending_customer", "resolved", "closed"]
    reason: Reason | None = None


class TicketAssign(_Input):
    assignee_id: uuid.UUID


class CommentCreate(_Input):
    body: LongText
    visibility: Literal["public", "internal"] = Field(
        description="public = reply the customer sees; internal = note for staff only."
    )


class PortalCommentCreate(_Input):
    body: LongText


class _Output(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TicketRead(_Output):
    """Staff view."""

    id: uuid.UUID
    number: int
    account_id: uuid.UUID
    requester_user_id: uuid.UUID | None
    subject: str
    description: str
    status: TicketStatus
    priority: TicketPriority
    channel: TicketChannel
    assignee_user_id: uuid.UUID | None
    first_response_due_at: datetime
    resolution_due_at: datetime
    first_responded_at: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None
    sla_state: SlaStateName
    category: str
    satisfaction_rating: int | None
    satisfaction_comment: str | None
    rated_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int


class TicketPage(BaseModel):
    items: list[TicketRead]
    total: int
    limit: int
    offset: int


class PortalTicketRead(_Output):
    """Customer view: no assignee, SLA, channel or internal data."""

    id: uuid.UUID
    number: int
    account_id: uuid.UUID
    subject: str
    description: str
    status: TicketStatus
    category: str
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    satisfaction_rating: int | None
    rated_at: datetime | None


class CommentRead(BaseModel):
    id: uuid.UUID
    ticket_id: uuid.UUID
    body: str
    visibility: Literal["public", "internal"]
    author_user_id: uuid.UUID | None
    author_name: str
    author_type: Literal["staff", "customer", "system"]
    created_at: datetime


class PortalCommentRead(BaseModel):
    id: uuid.UUID
    body: str
    author_name: str
    author_type: Literal["staff", "customer", "system"]
    created_at: datetime
