"""Knowledge search columns and indexes: embedding vector(384), generated tsv, HNSW + GIN (RAG R2).

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-21

The pgvector extension must exist before this migration (ADR 0010: it is created by the
superuser init script / one-off command, never by a migration). This migration checks that
clearly and stops otherwise.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EMBEDDING_DIMENSIONS = 384


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
                RAISE EXCEPTION
                    'pgvector is not enabled in this database. See docs/rag-runbook.md (R0).';
            END IF;
        END
        $$;
        """
    )
    op.add_column(
        "kb_chunks",
        sa.Column("embedding", Vector(_EMBEDDING_DIMENSIONS), nullable=True),
    )
    op.add_column(
        "kb_chunks",
        sa.Column("embedding_model", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "kb_chunks",
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('simple', heading_path || ' ' || text)",
                persisted=True,
            ),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_kb_chunks_embedding_hnsw",
        "kb_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_kb_chunks_tsv_gin",
        "kb_chunks",
        ["tsv"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_kb_chunks_tsv_gin", table_name="kb_chunks")
    op.drop_index("ix_kb_chunks_embedding_hnsw", table_name="kb_chunks")
    op.drop_column("kb_chunks", "tsv")
    op.drop_column("kb_chunks", "embedding_model")
    op.drop_column("kb_chunks", "embedding")
