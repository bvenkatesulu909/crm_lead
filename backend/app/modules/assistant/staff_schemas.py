"""Staff assistant contracts."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StaffQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    ticket_id: str | None = Field(default=None, max_length=40)


class ProposalRead(BaseModel):
    """A change the assistant proposed; it waits for a manager's approval (ADR 0014)."""

    id: uuid.UUID
    description: str
    status: str
    link: str


class StaffAnswer(BaseModel):
    answer: str
    ticket_id: uuid.UUID
    links: list[str]
    proposals: list[ProposalRead] = []


class TurnRead(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class StaffConversationRead(BaseModel):
    """A conversation with the staff assistant (ADR 0023). Only its owner can read it."""

    id: uuid.UUID
    turns: list[TurnRead] = []


class StaffTurnRequest(BaseModel):
    """One question in a conversation. ``mode: voice`` asks for a short answer to be read aloud.

    Nothing else is accepted: the conversation, the person and the organisation come from the URL
    and the verified token, the history from the server's own store."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)
    ticket_id: str | None = Field(default=None, max_length=40)
    mode: Literal["text", "voice"] = "text"
