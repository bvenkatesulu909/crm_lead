"""Communication Center: a database-assigned order for e-mail messages (step CC4).

Revision ID: 0039
Revises: 0038
Create Date: 2026-10-24

Histories and the Communication Center list show the newest e-mail first. ``created_at`` is not
enough: e-mails stored in the same instant (or the same transaction) get the same time. ``seq``
is an identity column, like ``audit_log.seq`` and ``contract_events.seq``, so the order is
always the order in which the rows were stored. Existing rows are numbered automatically.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "email_messages",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
    )
    op.create_index(
        "ix_email_messages_tenant_id_seq", "email_messages", ["tenant_id", "seq"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_email_messages_tenant_id_seq", table_name="email_messages")
    op.drop_column("email_messages", "seq")
