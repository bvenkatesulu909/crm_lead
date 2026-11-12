"""Request and response bodies of /api/v1/webcheck (ADR 0019).

The request holds only what the person chooses: which record, which source, what to look up.
The organisation and the person come from the verified token, and nobody can hand the server an
address: a source builds its own. Anything else in a request is refused, not ignored.
"""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


# --- company details on a lead (BP-02, ADR 0026) -------------------------------------------------

CompanyField = Literal["company_website", "company_industry", "company_size"]


class CompanyDetailsAsk(BaseModel):
    """Only the lead: the website to read is worked out by the server from the lead itself."""

    model_config = ConfigDict(extra="forbid")

    lead_id: uuid.UUID


class CompanyDetailsApply(BaseModel):
    """Which suggestions to keep. The values come from the stored evidence, never from here."""

    model_config = ConfigDict(extra="forbid")

    lead_id: uuid.UUID
    evidence_id: uuid.UUID
    fields: list[CompanyField] = Field(min_length=1, max_length=3)
    version: int = Field(ge=1, description="The lead's version from your last read.")

    @field_validator("fields")
    @classmethod
    def _once_each(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("name each field once")
        return value


class CompanyCurrent(BaseModel):
    company_website: str | None
    company_industry: str | None
    company_size: str | None
    version: int


class CompanySuggestionRead(BaseModel):
    """One lookup of the company's website: what it suggests and what that rests on (cleaned)."""

    id: uuid.UUID
    created_at: datetime
    verdict: Literal["found", "not_found", "unclear", "error"]
    error_code: str | None
    company_website: str | None
    company_industry: str | None
    company_size: str | None
    name: str | None
    excerpt: str
    pages: list[str]
    cleaned: list[str]


class CompanyDetailsRead(BaseModel):
    current: CompanyCurrent
    latest: CompanySuggestionRead | None
