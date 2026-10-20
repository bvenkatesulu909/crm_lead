"""Knowledge tables: uploaded documents and their chunks (RAG R1).

Every table is tenant-owned and RLS-ready (tenant_id + composite same-tenant FKs). Vectors and
keyword columns arrive in R2; this migration only prepares the text side.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantOwnedMixin, TimestampMixin, UUIDPrimaryKeyMixin

# processing -> indexed | needs_review | failed | no_text
DOCUMENT_STATUSES = ("processing", "indexed", "needs_review", "failed", "no_text")


def _sql_list(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


class KnowledgeDocument(UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, Base):
    """One uploaded knowledge file. Bytes live in the S3 file store, never in PostgreSQL."""

    __tablename__ = "kb_documents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        # The same file content is indexed once per tenant (avoids duplicate work/cost).
        UniqueConstraint("tenant_id", "sha256"),
        CheckConstraint(f"status IN {_sql_list(DOCUMENT_STATUSES)}", name="status_allowed"),
        CheckConstraint("size_bytes >= 0", name="size_not_negative"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
        Index("ix_kb_documents_tenant_id_status", "tenant_id", "status"),
        ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
        ),
    )

    title: Mapped[str] = mapped_column(String(200))
    file_name: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    # tenant/{tenant}/knowledge/{document}/{document} - built only from server-side IDs.
    storage_key: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), server_default=sa_text("'processing'"))
    page_count: Mapped[int] = mapped_column(Integer, server_default=sa_text("0"))
    # Safe, short error code/message only (never document text or personal data).
    error: Mapped[str | None] = mapped_column(String(300), default=None)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)


class KnowledgeChunk(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    """A few paragraphs under one heading - the unit retrieval will search (R2/R3)."""

    __tablename__ = "kb_chunks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "document_id", "chunk_no"),
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["kb_documents.tenant_id", "kb_documents.id"],
            ondelete="CASCADE",
        ),
        Index("ix_kb_chunks_tenant_id_document_id", "tenant_id", "document_id"),
        CheckConstraint("chunk_no >= 1", name="chunk_no_positive"),
        CheckConstraint("char_count >= 0", name="char_count_not_negative"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    chunk_no: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    # Paragraph blocks stay separate so a later answer can cite the exact sentences.
    blocks: Mapped[list[str]] = mapped_column(JSONB)
    heading_path: Mapped[str] = mapped_column(String(500), server_default=sa_text("''"))
    page_from: Mapped[int | None] = mapped_column(Integer, default=None)
    page_to: Mapped[int | None] = mapped_column(Integer, default=None)
    char_count: Mapped[int] = mapped_column(Integer)
    # Bump when the chunker changes; a rebuild then re-ingests documents.
    chunking_version: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
