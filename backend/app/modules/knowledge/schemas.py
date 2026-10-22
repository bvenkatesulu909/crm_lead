"""API schemas for knowledge documents (RAG R1)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


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
