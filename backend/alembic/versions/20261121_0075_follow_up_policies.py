"""Follow-up settings per organisation (ADR 0036, FM3).

Revision ID: 0075
Revises: 0074
Create Date: 2026-11-21

One row per change, newest wins; rows are never updated and are deleted only after a year (the
same guard the other insert-only tables have), so who switched automatic follow-ups on or off, and
with which numbers, can always be shown. The bounds are written out here on purpose: a migration
must not change when the code does.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0075"
down_revision: str | None = "0074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "follow_up_policies",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("monthly_cap", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column("daily_cap", sa.Integer(), server_default=sa.text("100"), nullable=False),
        sa.Column("pending_cap", sa.Integer(), server_default=sa.text("20"), nullable=False),
        sa.Column("expiry_days", sa.Integer(), server_default=sa.text("7"), nullable=False),
        sa.Column("cooldown_days", sa.Integer(), server_default=sa.text("7"), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "monthly_cap BETWEEN 1 AND 8", name=op.f("ck_follow_up_policies_monthly_cap_bounds")
        ),
        sa.CheckConstraint(
            "daily_cap BETWEEN 1 AND 100", name=op.f("ck_follow_up_policies_daily_cap_bounds")
        ),
        sa.CheckConstraint(
            "pending_cap BETWEEN 1 AND 20", name=op.f("ck_follow_up_policies_pending_cap_bounds")
        ),
        sa.CheckConstraint(
            "expiry_days BETWEEN 1 AND 30", name=op.f("ck_follow_up_policies_expiry_days_bounds")
        ),
        sa.CheckConstraint(
            "cooldown_days BETWEEN 1 AND 60",
            name=op.f("ck_follow_up_policies_cooldown_days_bounds"),
        ),
        sa.CheckConstraint(
            "NOT enabled OR template_id IS NOT NULL",
            name=op.f("ck_follow_up_policies_enabled_has_template"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_follow_up_policies_tenant_id_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "template_id"],
            ["email_templates.tenant_id", "email_templates.id"],
            name=op.f("fk_follow_up_policies_tenant_id_template_id_email_templates"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_follow_up_policies_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_follow_up_policies")),
    )
    op.create_index(
        "ix_follow_up_policies_tenant_id_seq", "follow_up_policies", ["tenant_id", "seq"]
    )

    op.execute("ALTER TABLE follow_up_policies ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE follow_up_policies FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY follow_up_policies_tenant_isolation ON follow_up_policies
            USING (tenant_id = crm_current_tenant())
            WITH CHECK (tenant_id = crm_current_tenant());
        """
    )
    op.execute(
        """
        CREATE FUNCTION follow_up_policies_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'UPDATE' THEN
            RAISE EXCEPTION 'follow_up_policies rows cannot be changed';
          END IF;
          IF OLD.created_at > now() - interval '365 days' THEN
            RAISE EXCEPTION 'follow_up_policies rows can be deleted only after 365 days';
          END IF;
          RETURN OLD;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER follow_up_policies_guard BEFORE UPDATE OR DELETE ON follow_up_policies
            FOR EACH ROW EXECUTE FUNCTION follow_up_policies_guard();
        """
    )
    op.execute(
        """
        DO $$
        DECLARE grantee_name text;
        BEGIN
          FOR grantee_name IN
            SELECT DISTINCT grantee FROM information_schema.role_table_grants
            WHERE table_schema = current_schema() AND table_name = 'follow_up_policies'
              AND privilege_type IN ('UPDATE', 'TRUNCATE')
              AND grantee <> current_user
          LOOP
            EXECUTE format('REVOKE UPDATE, TRUNCATE ON follow_up_policies FROM %I', grantee_name);
          END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS follow_up_policies_guard ON follow_up_policies;")
    op.execute("DROP FUNCTION IF EXISTS follow_up_policies_guard();")
    op.execute("DROP POLICY IF EXISTS follow_up_policies_tenant_isolation ON follow_up_policies;")
    op.drop_index("ix_follow_up_policies_tenant_id_seq", table_name="follow_up_policies")
    op.drop_table("follow_up_policies")
