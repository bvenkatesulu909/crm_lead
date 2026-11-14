"""Proposal decks as stored documents (ADR 0032, PD3).

Revision ID: 0064
Revises: 0063
Create Date: 2026-11-13

``documents.purpose`` may now be ``quote_deck``. A quote can have several decks over time (the
organisation changes its branding, so a new deck differs from the old one); the same bytes are
stored once per quote: a unique partial index on (organisation, record, sha256) for decks. A deck
is generated deterministically, so asking again with nothing changed finds the existing one.

The purpose list is written out here on purpose: a migration must not change when the code does.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0064"
down_revision: str | None = "0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_documents_purpose_allowed"), "documents", type_="check")
    op.create_check_constraint(
        op.f("ck_documents_purpose_allowed"),
        "documents",
        "purpose IN ('quote_pdf', 'attachment', 'quote_deck')",
    )
    # Two documents made in one transaction must still sort in the order they were made.
    op.execute("ALTER TABLE documents ALTER COLUMN created_at SET DEFAULT clock_timestamp();")
    op.create_index(
        "uq_documents_quote_deck_content",
        "documents",
        ["tenant_id", "record_type", "record_id", "sha256"],
        unique=True,
        postgresql_where="purpose = 'quote_deck'",
    )


def downgrade() -> None:
    op.execute("ALTER TABLE documents ALTER COLUMN created_at SET DEFAULT now();")
    op.drop_index("uq_documents_quote_deck_content", table_name="documents")
    op.execute("DELETE FROM documents WHERE purpose = 'quote_deck'")
    op.drop_constraint(op.f("ck_documents_purpose_allowed"), "documents", type_="check")
    op.create_check_constraint(
        op.f("ck_documents_purpose_allowed"),
        "documents",
        "purpose IN ('quote_pdf', 'attachment')",
    )
