"""Response of the video brief (ADR 0041). Read-only: nothing is accepted from the client except
the four choices, which are query parameters checked against fixed lists."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class KnownLineRead(BaseModel):
    kind: Literal["fact", "assumption", "form", "price"]
    key: str
    label: str
    value: str
    source: str | None
    quote: str | None
    reason: str | None


class ScriptLineRead(BaseModel):
    kind: Literal["greeting", "intro", "fact", "price", "question", "closing"]
    text: str
    cites: list[str]
    seconds: int


class CautionRead(BaseModel):
    code: str
    text: str


class VideoBriefRead(BaseModel):
    first_name: str
    language: Literal["en", "hi", "te"]
    tone: Literal["warm", "professional", "brisk"]
    tone_note: str
    goal: Literal["introduce", "follow_up", "after_visit", "explain_quote", "revive"]
    length_seconds: Literal[30, 60, 90]
    word_target: int
    words: int
    known: list[KnownLineRead]
    script: list[ScriptLineRead]
    must_say: list[str]
    must_not_say: list[str]
    consent_notes: list[str]
    cautions: list[CautionRead]


class ScriptCreate(BaseModel):
    """What a person sends to save a script. Nothing else is accepted: the lead comes from the
    address, and the version, the author and the organisation are the server's."""

    model_config = ConfigDict(extra="forbid")

    language: Literal["en", "hi", "te"]
    tone: Literal["warm", "professional", "brisk"]
    goal: Literal["introduce", "follow_up", "after_visit", "explain_quote", "revive"]
    length_seconds: Literal[30, 60, 90]
    lines: list[str] = Field(min_length=1, max_length=12)


class ScriptRead(BaseModel):
    id: uuid.UUID
    version: int
    source: Literal["hand_written", "ai_draft"]
    language: Literal["en", "hi", "te"]
    tone: Literal["warm", "professional", "brisk"]
    goal: Literal["introduce", "follow_up", "after_visit", "explain_quote", "revive"]
    length_seconds: Literal[30, 60, 90]
    lines: list[str]
    words: int
    created_by: uuid.UUID
    created_at: datetime


class ScriptPage(BaseModel):
    items: list[ScriptRead]


class DraftCreate(BaseModel):
    """What a person sends to ask for a draft. The facts are never sent: the server reads them as
    the person asking."""

    model_config = ConfigDict(extra="forbid")

    goal: Literal["introduce", "follow_up", "after_visit", "explain_quote", "revive"] = "follow_up"
    language: Literal["en", "hi", "te"] | None = None
    tone: Literal["warm", "professional", "brisk"] = "warm"
    length_seconds: Literal[30, 60, 90] = 60
    quote_id: uuid.UUID | None = None


class DraftRead(BaseModel):
    """A draft: shown to the person who asked, not saved and not approved."""

    status: Literal["draft"] = "draft"
    lines: list[str]
    words: int
    reason: str
    language: Literal["en", "hi", "te"]
    goal: Literal["introduce", "follow_up", "after_visit", "explain_quote", "revive"]
    tone: Literal["warm", "professional", "brisk"]
    length_seconds: Literal[30, 60, 90]
