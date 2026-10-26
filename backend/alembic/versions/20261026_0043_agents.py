"""AI agent registry: per-organisation settings and monthly usage (AG1).

Revision ID: 0043
Revises: 0042
Create Date: 2026-10-26

Two tables (ADR 0016): ``agent_settings`` (an organisation's overrides: on/off, monthly token
budget, allowed tools) and ``agent_usage`` (a monthly running total, counts only). Both get
ENABLE + FORCE row-level security and the tenant policy (ADR 0009); the guard test fails a tenant
table without it. Usage rows are history: DELETE and TRUNCATE are revoked from the application
role.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEY = "^[a-z][a-z_]{2,39}$"


def _timestamp(name: str) -> sa.Column[sa.DateTime]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY {table}_tenant_isolation ON {table}
            USING (tenant_id = crm_current_tenant())
            WITH CHECK (tenant_id = crm_current_tenant());
        """
    )


def upgrade() -> None:
    op.create_table(
        "agent_settings",
        sa.Column("agent_key", sa.String(length=40), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("monthly_token_budget", sa.BigInteger(), nullable=True),
        sa.Column("allowed_tools", postgresql.ARRAY(sa.String(length=60)), nullable=True),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(f"agent_key ~ '{_KEY}'", name=op.f("ck_agent_settings_agent_key_shape")),
        sa.CheckConstraint(
            "monthly_token_budget IS NULL OR monthly_token_budget BETWEEN 1 AND 10000000000",
            name=op.f("ck_agent_settings_budget_range"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "updated_by_user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_agent_settings_tenant_id_updated_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_agent_settings_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_settings")),
        sa.UniqueConstraint(
            "tenant_id", "agent_key", name=op.f("uq_agent_settings_tenant_id_agent_key")
        ),
    )
    op.create_table(
        "agent_usage",
        sa.Column("agent_key", sa.String(length=40), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("calls", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("warned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.CheckConstraint(f"agent_key ~ '{_KEY}'", name=op.f("ck_agent_usage_agent_key_shape")),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND calls >= 0",
            name=op.f("ck_agent_usage_counts_not_negative"),
        ),
        sa.CheckConstraint(
            "date_part('day', month) = 1", name=op.f("ck_agent_usage_month_is_first_day")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_agent_usage_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_usage")),
        sa.UniqueConstraint(
            "tenant_id", "agent_key", "month", name=op.f("uq_agent_usage_tenant_id_agent_key_month")
        ),
    )
    op.create_index("ix_agent_usage_tenant_id_month", "agent_usage", ["tenant_id", "month"])
    _rls("agent_settings")
    _rls("agent_usage")
    # Usage is history: counts are added to, but nothing may delete them.
    op.execute(
        """
        DO $$
        DECLARE grantee_name text;
        BEGIN
          FOR grantee_name IN
            SELECT DISTINCT grantee FROM information_schema.role_table_grants
            WHERE table_schema = current_schema() AND table_name = 'agent_usage'
              AND privilege_type IN ('DELETE', 'TRUNCATE')
              AND grantee <> current_user
          LOOP
            EXECUTE format('REVOKE DELETE, TRUNCATE ON agent_usage FROM %I', grantee_name);
          END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    for table in ("agent_usage", "agent_settings"):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};")
    op.drop_index("ix_agent_usage_tenant_id_month", table_name="agent_usage")
    op.drop_table("agent_usage")
    op.drop_table("agent_settings")
