"""API schemas for knowledge documents (RAG R1)."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class KnowledgeDocumentRead(BaseModel):
    id: uuid.UUID
    title: str
    file_name: str
    content_type: str
    size_bytes: int
    status: str
    page_count: int
    chunk_count: int
    error: str | None
    created_at: datetime


class KnowledgeDocumentList(BaseModel):
    items: list[KnowledgeDocumentRead]
    total: int
