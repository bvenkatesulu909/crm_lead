"""PowerPoint proposal decks as stored documents (ADR 0032 Amendment A, PD6b).

Revision ID: 0065
Revises: 0064
Create Date: 2026-11-14

``documents.purpose`` may now be ``quote_deck_pptx``: the PowerPoint file of a proposal deck is its
own kind of document, so a new PowerPoint never replaces the PDF (``quote_deck``) and the newest of
each kind can be found on its own. Like the PDF, the same bytes are stored once per quote: a second
unique partial index on (organisation, record, sha256) for the new purpose.

The purpose list is written out here on purpose: a migration must not change when the code does.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0065"
down_revision: str | None = "0064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_documents_purpose_allowed"), "documents", type_="check")
    op.create_check_constraint(
        op.f("ck_documents_purpose_allowed"),
        "documents",
        "purpose IN ('quote_pdf', 'attachment', 'quote_deck', 'quote_deck_pptx')",
    )
    op.create_index(
        "uq_documents_quote_deck_pptx_content",
        "documents",
        ["tenant_id", "record_type", "record_id", "sha256"],
        unique=True,
        postgresql_where="purpose = 'quote_deck_pptx'",
    )


def downgrade() -> None:
    op.drop_index("uq_documents_quote_deck_pptx_content", table_name="documents")
    op.execute("DELETE FROM documents WHERE purpose = 'quote_deck_pptx'")
    op.drop_constraint(op.f("ck_documents_purpose_allowed"), "documents", type_="check")
    op.create_check_constraint(
        op.f("ck_documents_purpose_allowed"),
        "documents",
        "purpose IN ('quote_pdf', 'attachment', 'quote_deck')",
    )
