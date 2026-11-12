"""Request and response bodies of buyer memory (ADR 0028).

The server decides the tenant, the lead (from the URL, checked), who recorded it, the order and the
time - none of them can be sent. The API accepts only the two sources a person can vouch for."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.modules.buyer_memory.rules import API_SOURCES  # noqa: F401 - documents the Literal below

# A generous cap only to stop huge payloads; the rules enforce the real 300 after cleaning.
Text = Annotated[str, StringConstraints(max_length=1200)]
ApiSource = Literal["timeline_entry", "buyer_confirmed"]


class MemoryItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: Annotated[str, StringConstraints(max_length=40)]
    value: Text
    status: Annotated[str, StringConstraints(max_length=20)]
    source: ApiSource | None = None
    source_ref: uuid.UUID | None = None
    quote: Text | None = None
    reason: Text | None = None


class MemoryConfirm(BaseModel):
    """Confirm an assumption: a new fact with the same key. ``value`` may correct it."""

    model_config = ConfigDict(extra="forbid")

    source: ApiSource
    source_ref: uuid.UUID | None = None
    quote: Text
    value: Text | None = None


class MemoryKeyRead(BaseModel):
    key: str
    label: str


class MemoryItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    value: str
    status: Literal["fact", "assumption"]
    source: str | None
    source_ref: uuid.UUID | None
    quote: str | None
    reason: str | None
    recorded_by_user_id: uuid.UUID
    created_at: datetime


class MemoryRead(BaseModel):
    keys: list[MemoryKeyRead]
    current: list[MemoryItemRead]
    history: list[MemoryItemRead]
    gaps: list[MemoryKeyRead]


class CopyResult(BaseModel):
    added: int
