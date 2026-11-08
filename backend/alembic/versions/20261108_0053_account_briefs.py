"""Account research: stored account briefs (DD4)

Revision ID: 0053
Revises: 0052
Create Date: 2026-11-08

ADR 0024. One new table, ``account_briefs``: ENABLE + FORCE row-level security and the tenant
policy (ADR 0009), plus the same two locks as ``deal_reviews`` (a trigger refuses every UPDATE and a
DELETE of a row younger than 365 days; the application role loses UPDATE and TRUNCATE).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0053"
down_revision: str | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    jsonb = sa.dialects.postgresql.JSONB()
    op.create_table(
        "account_briefs",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("sentences", jsonb, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("dropped", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("gathered", jsonb, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "jsonb_typeof(sentences) = 'array'", name=op.f("ck_account_briefs_sentences_is_list")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(gathered) = 'object'", name=op.f("ck_account_briefs_gathered_is_object")
        ),
        sa.CheckConstraint("dropped >= 0", name=op.f("ck_account_briefs_dropped_not_negative")),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0",
            name=op.f("ck_account_briefs_tokens_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            ["accounts.tenant_id", "accounts.id"],
            name=op.f("fk_account_briefs_tenant_id_account_id_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "requested_by_user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_account_briefs_tenant_id_requested_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_account_briefs_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_briefs")),
    )
    op.create_index(
        "ix_account_briefs_tenant_id_account_id",
        "account_briefs",
        ["tenant_id", "account_id", "seq"],
    )
    op.execute("ALTER TABLE account_briefs ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE account_briefs FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY account_briefs_tenant_isolation ON account_briefs
            USING (tenant_id = crm_current_tenant())
            WITH CHECK (tenant_id = crm_current_tenant());
        """
    )
    op.execute(
        """
        CREATE FUNCTION account_briefs_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'UPDATE' THEN
            RAISE EXCEPTION 'account_briefs rows cannot be changed';
          END IF;
          IF OLD.created_at > now() - interval '365 days' THEN
            RAISE EXCEPTION 'account_briefs rows can be deleted only after 365 days';
          END IF;
          RETURN OLD;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER account_briefs_guard BEFORE UPDATE OR DELETE ON account_briefs
            FOR EACH ROW EXECUTE FUNCTION account_briefs_guard();
        """
    )
    op.execute(
        """
        DO $$
        DECLARE grantee_name text;
        BEGIN
          FOR grantee_name IN
            SELECT DISTINCT grantee FROM information_schema.role_table_grants
            WHERE table_schema = current_schema() AND table_name = 'account_briefs'
              AND privilege_type IN ('UPDATE', 'TRUNCATE')
              AND grantee <> current_user
          LOOP
            EXECUTE format('REVOKE UPDATE, TRUNCATE ON account_briefs FROM %I', grantee_name);
          END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS account_briefs_guard ON account_briefs;")
    op.execute("DROP FUNCTION IF EXISTS account_briefs_guard();")
    op.execute("DROP POLICY IF EXISTS account_briefs_tenant_isolation ON account_briefs;")
    op.drop_index("ix_account_briefs_tenant_id_account_id", table_name="account_briefs")
    op.drop_table("account_briefs")
