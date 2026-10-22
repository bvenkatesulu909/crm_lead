"""Knowledge tables: uploaded documents and their chunks (RAG R1 + R2).

Every table is tenant-owned and RLS-ready (tenant_id + composite same-tenant FKs). Chunks carry a
384-dimension embedding (meaning search) and a generated keyword column (word search), both indexed.
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
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
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantOwnedMixin, TimestampMixin, UUIDPrimaryKeyMixin

# processing -> indexed | needs_review | failed | no_text
DOCUMENT_STATUSES = ("processing", "indexed", "needs_review", "failed", "no_text")
# Who may read a document: internal = staff only; customer_visible = later, portal users too.
VISIBILITIES = ("internal", "customer_visible")


def _sql_list(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


class KnowledgeDocument(UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, Base):
    """One uploaded knowledge file. Bytes live in the S3 file store, never in PostgreSQL."""

    __tablename__ = "kb_documents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "group_id", "version"),
        Index("ix_kb_documents_tenant_id_archived", "tenant_id", "is_archived"),
        # The same file content is indexed once per tenant (avoids duplicate work/cost).
        UniqueConstraint("tenant_id", "sha256"),
        CheckConstraint(f"status IN {_sql_list(DOCUMENT_STATUSES)}", name="status_allowed"),
        CheckConstraint("size_bytes >= 0", name="size_not_negative"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
        CheckConstraint(f"visibility IN {_sql_list(VISIBILITIES)}", name="visibility_allowed"),
        Index("ix_kb_documents_tenant_id_status", "tenant_id", "status"),
        Index("ix_kb_documents_tenant_id_visibility", "tenant_id", "visibility"),
        Index("ix_kb_documents_tenant_id_account_id", "tenant_id", "account_id"),
        ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            ["accounts.tenant_id", "accounts.id"],
            ondelete="CASCADE",
        ),
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
    # Record-level scope (R3): copied onto chunks too, so search filters before ranking.
    visibility: Mapped[str] = mapped_column(String(30), server_default=sa_text("'internal'"))
    # Versions of one logical document share a group; archiving deletes the chunks.
    group_id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    version: Mapped[int] = mapped_column(Integer, server_default=sa_text("1"))
    is_archived: Mapped[bool] = mapped_column(Boolean, server_default=sa_text("false"))
    archived_at: Mapped[datetime | None] = mapped_column(default=None)
    # Optional customer account scope (portal); NULL + customer_visible = public to the tenant's
    # portal users. Copied to chunks so retrieval can filter before ranking.
    account_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
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
        # Meaning search index (ADR 0010/0011): approximate nearest neighbour, cosine distance.
        Index(
            "ix_kb_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        # Word search index over the generated keyword column.
        Index("ix_kb_chunks_tsv_gin", "tsv", postgresql_using="gin"),
        Index("ix_kb_chunks_tenant_id_visibility", "tenant_id", "visibility"),
        Index("ix_kb_chunks_tenant_id_account_id", "tenant_id", "account_id"),
        ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            ["accounts.tenant_id", "accounts.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(f"visibility IN {_sql_list(VISIBILITIES)}", name="visibility_allowed"),
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
    visibility: Mapped[str] = mapped_column(String(30), server_default=sa_text("'internal'"))
    account_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    # Meaning search (R2): 384 numbers from the local model, plus which model produced them.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384), default=None)
    embedding_model: Mapped[str | None] = mapped_column(String(100), default=None)
    # Word search (R2): kept in sync by PostgreSQL itself, so it can never drift from the text.
    tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', heading_path || ' ' || text)", persisted=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


RAG_SURFACES = ("staff_search", "staff_answer", "portal_answer")


class RagQuery(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    __tablename__ = "rag_queries"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_rag_queries_tenant_id_id"),
        CheckConstraint(f"surface IN {_sql_list(RAG_SURFACES)}", name="surface_allowed"),
        CheckConstraint("question <> ''", name="question_not_empty"),
        Index("ix_rag_queries_tenant_id_created_at", "tenant_id", "created_at"),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], ondelete="CASCADE"
        ),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    surface: Mapped[str] = mapped_column(String(30))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text, default=None)
    sources: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, server_default=sa_text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class RagFeedback(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    __tablename__ = "rag_feedback"
    __table_args__ = (
        UniqueConstraint("tenant_id", "query_id", "user_id", name="uq_rag_feedback_query_user"),
        ForeignKeyConstraint(
            ["tenant_id", "query_id"],
            ["rag_queries.tenant_id", "rag_queries.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], ondelete="CASCADE"
        ),
    )

    query_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    helpful: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
