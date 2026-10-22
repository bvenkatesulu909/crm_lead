"""Knowledge versions, archival and RAG retention support (R6.2/R6.3).

Revision ID: 0028
Revises: 0027
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "kb_documents",
        sa.Column(
            "group_id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
    )
    op.add_column(
        "kb_documents",
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.add_column(
        "kb_documents",
        sa.Column("is_archived", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "kb_documents", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_unique_constraint(
        "uq_kb_documents_tenant_id_group_id_version",
        "kb_documents",
        ["tenant_id", "group_id", "version"],
    )
    op.create_index(
        "ix_kb_documents_tenant_id_archived", "kb_documents", ["tenant_id", "is_archived"]
    )


def downgrade() -> None:
    op.drop_index("ix_kb_documents_tenant_id_archived", table_name="kb_documents")
    op.drop_constraint("uq_kb_documents_tenant_id_group_id_version", "kb_documents", type_="unique")
    op.drop_column("kb_documents", "archived_at")
    op.drop_column("kb_documents", "is_archived")
    op.drop_column("kb_documents", "version")
    op.drop_column("kb_documents", "group_id")
