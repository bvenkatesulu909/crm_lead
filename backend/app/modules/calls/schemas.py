"""Request and response bodies of call recordings (ADR 0030).

The server decides the tenant, the lead (from the URL, checked), who added it, the status, the
keys of the stored files and the transcript - none of them can be sent."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints, field_validator


class UploadStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_name: Annotated[str, StringConstraints(min_length=1, max_length=400)]
    size_bytes: Annotated[int, Field(ge=1)]
    language: Literal["hi", "te", "en"]
    # The buyer agreed to the call being recorded: only an explicit true (ADR 0030, CA5). A strict
    # boolean: the number 1 or the text "yes" is not consent.
    consent: StrictBool

    @field_validator("consent")
    @classmethod
    def _consent_given(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("The buyer must have agreed to the call being recorded.")
        return value


class UploadTicket(BaseModel):
    call_id: uuid.UUID
    url: str
    fields: dict[str, str]
    expires_at: datetime
    max_bytes: int


class CallRead(BaseModel):
    """A recording as the list shows it: no transcript text (that is a separate, heavier read)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lead_id: uuid.UUID
    added_by_user_id: uuid.UUID
    language: Literal["hi", "te", "en"]
    status: str
    failure_code: str | None
    file_name: str
    size_bytes: int | None
    duration_seconds: int | None
    consent_confirmed_at: datetime
    created_at: datetime
    finished_at: datetime | None
    audio_available: bool
    audio_deleted_at: datetime | None
    has_transcript: bool
    engine: str | None


class CallDetail(CallRead):
    """One recording with its transcript (always an automatic one - the screen says so)."""

    transcript: str | None
    segments: list[dict[str, Any]] | None


class CallPage(BaseModel):
    items: list[CallRead]


class ListenLink(BaseModel):
    url: str
    expires_in_seconds: int
    which: Literal["original", "cleaned"]
