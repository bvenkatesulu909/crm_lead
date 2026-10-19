"""Document uploads with versions on accounts and deals (Phase 10).

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-19 10:55:04.502588+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Versions: every version of a document shares the first version's id as its group.
    op.add_column("documents", sa.Column("group_id", sa.Uuid(), nullable=True))
    op.add_column(
        "documents",
        sa.Column("version_no", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.add_column("documents", sa.Column("description", sa.String(length=500), nullable=True))
    op.execute("UPDATE documents SET group_id = id WHERE group_id IS NULL")  # existing quote PDFs
    op.alter_column("documents", "group_id", nullable=False)
    op.create_unique_constraint(
        op.f("uq_documents_tenant_id_group_id_version_no"),
        "documents",
        ["tenant_id", "group_id", "version_no"],
    )
    op.create_check_constraint(
        op.f("ck_documents_version_positive"), "documents", "version_no >= 1"
    )
    op.create_index(
        "ix_documents_tenant_id_record",
        "documents",
        ["tenant_id", "record_type", "record_id"],
        unique=False,
    )

    # Uploads: documents on accounts and deals, many per record.
    op.drop_constraint(op.f("ck_documents_record_type_allowed"), "documents", type_="check")
    op.create_check_constraint(
        op.f("ck_documents_record_type_allowed"),
        "documents",
        "record_type IN ('quote', 'account', 'opportunity')",
    )
    op.drop_constraint(op.f("ck_documents_purpose_allowed"), "documents", type_="check")
    op.create_check_constraint(
        op.f("ck_documents_purpose_allowed"),
        "documents",
        "purpose IN ('quote_pdf', 'attachment')",
    )
    # "One per record" now applies only to generated quote PDFs.
    op.drop_index("uq_documents_one_generated_per_record", table_name="documents")
    op.create_index(
        "uq_documents_one_generated_per_record",
        "documents",
        ["tenant_id", "record_type", "record_id", "purpose"],
        unique=True,
        postgresql_where=sa.text("purpose = 'quote_pdf'"),
    )


def downgrade() -> None:
    op.execute("DELETE FROM documents WHERE purpose = 'attachment'")
    op.drop_index("uq_documents_one_generated_per_record", table_name="documents")
    op.create_index(
        "uq_documents_one_generated_per_record",
        "documents",
        ["tenant_id", "record_type", "record_id", "purpose"],
        unique=True,
    )
    op.drop_constraint(op.f("ck_documents_purpose_allowed"), "documents", type_="check")
    op.create_check_constraint(
        op.f("ck_documents_purpose_allowed"), "documents", "purpose IN ('quote_pdf')"
    )
    op.drop_constraint(op.f("ck_documents_record_type_allowed"), "documents", type_="check")
    op.create_check_constraint(
        op.f("ck_documents_record_type_allowed"), "documents", "record_type IN ('quote')"
    )
    op.drop_index("ix_documents_tenant_id_record", table_name="documents")
    op.drop_constraint(op.f("ck_documents_version_positive"), "documents", type_="check")
    op.drop_constraint(
        op.f("uq_documents_tenant_id_group_id_version_no"), "documents", type_="unique"
    )
    op.drop_column("documents", "description")
    op.drop_column("documents", "version_no")
    op.drop_column("documents", "group_id")
