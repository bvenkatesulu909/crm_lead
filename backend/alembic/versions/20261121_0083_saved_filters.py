"""Saved filters of the Accounts list (ADR 0042, BR-pre).

Revision ID: 0083
Revises: 0082
Create Date: 2026-11-21

One new tenant table. A saved filter is a name plus the list's own filter parameters, private to its
owner until shared with the organisation. ENABLE + FORCE row-level security and the tenant policy
(ADR 0009); who sees a private filter is decided in the queries, as for other owned records.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0083"
down_revision: str | None = "0082"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "saved_filters",
        sa.Column("record_type", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("shared", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "record_type IN ('account')", name=op.f("ck_saved_filters_record_type_allowed")
        ),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 80", name=op.f("ck_saved_filters_name_length")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(params) = 'object'", name=op.f("ck_saved_filters_params_is_object")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_saved_filters_tenant_id_owner_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_saved_filters_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_filters")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_saved_filters_tenant_id_id")),
    )
    op.create_index(
        "uq_saved_filters_owner_name",
        "saved_filters",
        ["tenant_id", "owner_user_id", "record_type", sa.text("lower(name)")],
        unique=True,
    )
    op.create_index(
        "uq_saved_filters_shared_name",
        "saved_filters",
        ["tenant_id", "record_type", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("shared"),
    )
    op.execute("ALTER TABLE saved_filters ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE saved_filters FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY saved_filters_tenant_isolation ON saved_filters
            USING (tenant_id = crm_current_tenant())
            WITH CHECK (tenant_id = crm_current_tenant());
        """
    )


def downgrade() -> None:
    op.drop_table("saved_filters")
