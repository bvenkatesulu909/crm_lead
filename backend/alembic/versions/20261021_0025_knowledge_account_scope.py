"""Account-scoped, customer-visible knowledge for the portal (RAG portal R4.3).

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-21

knowledge documents/chunks may optionally belong to ONE customer account (composite tenant FK).
Portal retrieval sees customer_visible chunks with no account (public) plus chunks of accounts the
customer has a portal_access_grants row for. Internal documents are never visible to customers.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("kb_documents", "kb_chunks"):
        op.add_column(table, sa.Column("account_id", sa.Uuid(), nullable=True))
        op.create_index(f"ix_{table}_tenant_id_account_id", table, ["tenant_id", "account_id"])
        op.create_foreign_key(
            f"fk_{table}_tenant_id_account_id_accounts",
            table,
            "accounts",
            ["tenant_id", "account_id"],
            ["tenant_id", "id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    for table in ("kb_chunks", "kb_documents"):
        op.drop_constraint(f"fk_{table}_tenant_id_account_id_accounts", table, type_="foreignkey")
        op.drop_index(f"ix_{table}_tenant_id_account_id", table_name=table)
        op.drop_column(table, "account_id")
