"""Request and response bodies of /api/v1/webcheck (ADR 0019).

The request holds only what the person chooses: which record, which source, what to look up.
The organisation and the person come from the verified token, and nobody can hand the server an
address: a source builds its own. Anything else in a request is refused, not ignored.
"""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WebCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: str = Field(min_length=1, max_length=20, description="lead or account")
    target_id: uuid.UUID
    source_key: str = Field(min_length=1, max_length=60)
    query: str = Field(min_length=1, max_length=200)


class WebCheckAccepted(BaseModel):
    request_id: uuid.UUID
    # The page is fetched by the worker: the result appears as evidence, and the asker is told.
    status: Literal["checking"] = "checking"


class WebCheckSourceRead(BaseModel):
    key: str
    title: str
    kind: Literal["rera", "company"]
    query_hint: str
    demo: bool


class WebCheckSourcePage(BaseModel):
    items: list[WebCheckSourceRead]


class WebEvidenceRead(BaseModel):
    """What was found, cleaned. The page's hash, the row's tenant and its order key stay inside."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    request_id: uuid.UUID
    source_key: str
    query: str
    requested_by_user_id: uuid.UUID
    verdict: Literal["found", "not_found", "unclear", "error"]
    error_code: str | None
    http_status: int | None
    final_url: str | None
    registered_name: str | None
    status: str | None
    valid_until: date | None
    excerpt: str
    cleaned: list[str]
    created_at: datetime


class WebEvidencePage(BaseModel):
    items: list[WebEvidenceRead]
