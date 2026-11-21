"""Response of the video brief (ADR 0041). Read-only: nothing is accepted from the client except
the four choices, which are query parameters checked against fixed lists."""

from typing import Literal

from pydantic import BaseModel


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
