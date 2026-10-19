"""Request/response contracts of the assistant (customer portal)."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

MAX_MESSAGE_CHARS = 2_000

UserText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_MESSAGE_CHARS)
]


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: uuid.UUID | None = None
    text: UserText


class MessageRead(BaseModel):
    id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class PendingActionRead(BaseModel):
    id: uuid.UUID
    kind: Literal["create_ticket"]
    status: Literal["pending", "confirmed", "cancelled"]
    account_name: str
    subject: str
    description: str
    ticket_number: int | None


class ConversationSummary(BaseModel):
    id: uuid.UUID
    title: str
    updated_at: datetime


class ConversationRead(ConversationSummary):
    messages: list[MessageRead]
    actions: list[PendingActionRead]


class AssistantStatus(BaseModel):
    available: bool
