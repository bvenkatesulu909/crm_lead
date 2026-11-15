"""Response of the rep's brief before a site visit (ADR 0029). Read-only: nothing is accepted from
the client except the optional place, a query parameter checked by the rules."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class BriefBuyer(BaseModel):
    name: str
    status: str
    source: str | None
    owner: str | None
    phone: str | None
    email: str | None
    language: Literal["en", "hi", "te"] | None
    language_label: str | None


class BriefFact(BaseModel):
    key: str
    label: str
    value: str
    source: str | None
    quote: str | None
    recorded_on: datetime


class BriefAssumption(BaseModel):
    key: str
    label: str
    value: str
    reason: str | None
    recorded_on: datetime


class BriefAsk(BaseModel):
    kind: Literal["confirm", "gap"]
    key: str
    label: str
    text: str


class BriefEntry(BaseModel):
    kind: str
    occurred_at: datetime
    subject: str
    excerpt: str


class BriefTask(BaseModel):
    subject: str
    due_at: datetime | None
    priority: str
    overdue: bool


class BriefCaution(BaseModel):
    code: str
    text: str


class BriefRead(BaseModel):
    as_of: datetime
    place: str | None
    buyer: BriefBuyer
    facts: list[BriefFact]
    assumptions: list[BriefAssumption]
    ask: list[BriefAsk]
    recent: list[BriefEntry]
    tasks: list[BriefTask]
    cautions: list[BriefCaution]
