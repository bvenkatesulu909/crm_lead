"""Knowledge ingestion tables: kb_documents and kb_chunks (RAG R1, ADR 0010/0011).

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-20

RLS: every table carries tenant_id and composite same-tenant FKs, so the RLS migration
(ADR 0009) can enable policies later without changing these tables. No policies yet.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kb_documents",
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("file_name", sa.String(length=200), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=300), nullable=False),
        sa.Column(
            "status", sa.String(length=20), server_default=sa.text("'processing'"), nullable=False
        ),
        sa.Column("page_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error", sa.String(length=300), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('processing', 'indexed', 'needs_review', 'failed', 'no_text')",
            name=op.f("ck_kb_documents_status_allowed"),
        ),
        sa.CheckConstraint("size_bytes >= 0", name=op.f("ck_kb_documents_size_not_negative")),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_kb_documents_sha256_hex")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_kb_documents_tenant_id_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_kb_documents_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kb_documents")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_kb_documents_tenant_id_id")),
        sa.UniqueConstraint("tenant_id", "sha256", name=op.f("uq_kb_documents_tenant_id_sha256")),
    )
    op.create_index(
        "ix_kb_documents_tenant_id_status", "kb_documents", ["tenant_id", "status"], unique=False
    )

    op.create_table(
        "kb_chunks",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_no", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("blocks", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "heading_path", sa.String(length=500), server_default=sa.text("''"), nullable=False
        ),
        sa.Column("page_from", sa.Integer(), nullable=True),
        sa.Column("page_to", sa.Integer(), nullable=True),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("chunking_version", sa.String(length=20), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("chunk_no >= 1", name=op.f("ck_kb_chunks_chunk_no_positive")),
        sa.CheckConstraint("char_count >= 0", name=op.f("ck_kb_chunks_char_count_not_negative")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["kb_documents.tenant_id", "kb_documents.id"],
            name=op.f("fk_kb_chunks_tenant_id_document_id_kb_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_kb_chunks_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kb_chunks")),
        sa.UniqueConstraint(
            "tenant_id",
            "document_id",
            "chunk_no",
            name=op.f("uq_kb_chunks_tenant_id_document_id_chunk_no"),
        ),
    )
    op.create_index(
        "ix_kb_chunks_tenant_id_document_id",
        "kb_chunks",
        ["tenant_id", "document_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_kb_chunks_tenant_id_document_id", table_name="kb_chunks")
    op.drop_table("kb_chunks")
    op.drop_index("ix_kb_documents_tenant_id_status", table_name="kb_documents")
    op.drop_table("kb_documents")
