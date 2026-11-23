"""Request and response bodies of the photo enhancer (ADR 0039).

The server decides the tenant, who asked, the state, the failure code, the copy and its facts. The
adjustments are read by ``rules.operations_from_dict`` (strict: unknown, mistyped or too-strong
values are refused), so the body only says which photo and passes the adjustments on."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool


class EnhancementCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: uuid.UUID
    operations: dict[str, Any] = Field(default_factory=dict)


class DeckChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    in_decks: StrictBool


class EnhancementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_document_id: uuid.UUID
    status: str
    failure_code: str | None
    operations: dict[str, Any]
    applied: list[str] | None
    width: int | None
    height: int | None
    size_bytes: int | None
    in_decks: bool
    created_at: datetime
    finished_at: datetime | None


class EnhancementPage(BaseModel):
    items: list[EnhancementRead]
    # What the screen shows beside an adjusted copy and prints in decks (ADR 0039 PE4).
    caption: str


class CopyLink(BaseModel):
    url: str
    file_name: str
    expires_at: datetime
