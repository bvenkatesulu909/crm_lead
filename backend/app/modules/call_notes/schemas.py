"""Request and response shapes of the call notes API (ADR 0035, CN3).

Input schemas accept only the fields a client may send; the tenant, the lead, the frame of a run,
the version and every count are the server's.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FieldRead(BaseModel):
    key: str
    label: str
    hint: str


class FrameworkRead(BaseModel):
    key: str
    title: str
    fields: list[FieldRead]


class SettingsRead(BaseModel):
    framework: str
    # 0 until an administrator chooses; then the version to send back with the next change.
    version: int
    frameworks: list[FrameworkRead]


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    framework: Literal["bant", "meddic"]
    version: int | None = Field(default=None, ge=0)


class LineRead(BaseModel):
    position: int
    field: str
    label: str
    state: str
    value: str | None
    quote: str | None
    start_ms: int | None
    end_ms: int | None
    reason: str | None
    # Why a claim was turned into "unknown" (for example quote_not_found), if it was.
    note_code: str | None


class NotesRead(BaseModel):
    id: uuid.UUID
    version_no: int
    framework: str
    requested_by_user_id: uuid.UUID
    model_name: str
    downgraded: int
    dropped_notes: int
    # Kinds of finding made while cleaning (link, instruction_phrase...), never the text.
    cleaned_codes: list[str]
    created_at: datetime
    lines: list[LineRead]


class VersionRead(BaseModel):
    version_no: int
    framework: str
    requested_by_user_id: uuid.UUID
    created_at: datetime


class NotesPage(BaseModel):
    newest: NotesRead | None
    versions: list[VersionRead]
