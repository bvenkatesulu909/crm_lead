"""Staff assistant contracts."""

import uuid

from pydantic import BaseModel, Field


class StaffQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    ticket_id: str | None = Field(default=None, max_length=40)


class StaffAnswer(BaseModel):
    answer: str
    ticket_id: uuid.UUID
    links: list[str]
