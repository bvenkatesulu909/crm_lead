"""Staff assistant contracts."""

import uuid

from pydantic import BaseModel, Field


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
