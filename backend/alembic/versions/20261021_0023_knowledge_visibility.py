"""Knowledge visibility (record-level scope) for retrieval (RAG R3).

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-21

Documents and chunks get a visibility so search can filter BEFORE ranking: internal (staff only)
and customer_visible (for the future customer portal). Existing rows default to internal.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("kb_documents", "kb_chunks"):
        op.add_column(
            table,
            sa.Column(
                "visibility",
                sa.String(length=30),
                server_default=sa.text("'internal'"),
                nullable=False,
            ),
        )
        op.create_check_constraint(
            op.f(f"ck_{table}_visibility_allowed"),
            table,
            "visibility IN ('internal', 'customer_visible')",
        )
        op.create_index(
            op.f(f"ix_{table}_tenant_id_visibility"),
            table,
            ["tenant_id", "visibility"],
            unique=False,
        )


def downgrade() -> None:
    for table in ("kb_chunks", "kb_documents"):
        op.drop_index(op.f(f"ix_{table}_tenant_id_visibility"), table_name=table)
        op.drop_constraint(op.f(f"ck_{table}_visibility_allowed"), table, type_="check")
        op.drop_column(table, "visibility")
