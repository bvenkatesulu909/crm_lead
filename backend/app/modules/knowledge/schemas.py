"""API schemas for knowledge documents (RAG R1)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeDocumentRead(BaseModel):
    id: uuid.UUID
    title: str
    file_name: str
    content_type: str
    size_bytes: int
    status: str
    visibility: str
    account_id: uuid.UUID | None
    group_id: uuid.UUID
    version: int
    is_archived: bool
    page_count: int
    chunk_count: int
    error: str | None
    created_at: datetime


class KnowledgeDocumentList(BaseModel):
    items: list[KnowledgeDocumentRead]
    total: int


class KnowledgeAnswerRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class KnowledgeAnswerSource(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    heading_path: str
    page_from: int | None
    page_to: int | None
    text: str


class RagFeedbackCreate(BaseModel):
    query_id: uuid.UUID
    helpful: bool


class KnowledgeAnswerResponse(BaseModel):
    query_id: uuid.UUID | None = None
    answer: str
    sources: list[KnowledgeAnswerSource]
    exact_chunk_id: uuid.UUID | None
    enough: bool
    model_used: bool
    # R5 evaluation signals: the answer's citations were checked against the given sources.
    grounded: bool
    citations: list[int]
    # Why the answer was refused, as a code (None when answered): not_found, ungrounded,
    # rera_not_found, rera_not_cited, price_not_cited (CRM-115). The screen words it.
    refusal_reason: str | None = None


class KnowledgeSearchHit(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    file_name: str
    heading_path: str
    page_from: int | None
    page_to: int | None
    text: str
    blocks: list[str]
    visibility: str
    similarity: float | None
    keyword_rank: int | None
    score: float
    rerank_score: float | None


class KnowledgeSearchResponse(BaseModel):
    query: str
    results: list[KnowledgeSearchHit]
    best_similarity: float | None
    threshold: float | None
    enough: bool


class KnowledgeUploadStart(BaseModel):
    """What a browser says before it sends a knowledge file straight to the store (ADR 0025)."""

    model_config = ConfigDict(extra="forbid")

    file_name: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=1)
    title: str | None = Field(default=None, max_length=200)
    visibility: str = "internal"
    account_id: uuid.UUID | None = None
    replaces_document_id: uuid.UUID | None = None


class KnowledgeUploadTicket(BaseModel):
    """POST every field in ``fields`` to ``url`` with the file last (field ``file``), then call
    ``finish`` with ``upload_id``."""

    upload_id: uuid.UUID
    url: str
    fields: dict[str, str]
    expires_at: datetime
    max_bytes: int
