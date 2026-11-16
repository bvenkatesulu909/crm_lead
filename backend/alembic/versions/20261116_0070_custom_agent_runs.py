"""Runs and dry runs of custom agents (ADR 0034, AB2b).

Revision ID: 0070
Revises: 0069
Create Date: 2026-11-16

One new table, ``custom_agent_runs``: which version of which agent ran on which record, who asked,
and what came of it (ids and codes only, never what the model wrote). ENABLE + FORCE row-level
security and the tenant policy (ADR 0009), and the two locks the other insert-only tables have: a
trigger refuses every UPDATE and a DELETE of a row younger than 365 days, and the application role
loses UPDATE and TRUNCATE.

A dry run ("trial") never proposes, a real run's outcome ``proposed`` always has its proposal: the
database keeps that straight. A successful dry run of the current version is what lets an agent be
switched on.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0070"
down_revision: str | None = "0069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "custom_agent_runs",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("custom_agent_id", sa.Uuid(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=5), nullable=False),
        sa.Column("record_type", sa.String(length=10), nullable=False),
        sa.Column("record_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=12), nullable=False),
        sa.Column("outcome", sa.String(length=12), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "mode IN ('run', 'trial')", name=op.f("ck_custom_agent_runs_mode_allowed")
        ),
        sa.CheckConstraint(
            "outcome IN ('proposed', 'no_proposal', 'blocked', 'shown')",
            name=op.f("ck_custom_agent_runs_outcome_allowed"),
        ),
        sa.CheckConstraint(
            "record_type IN ('lead', 'account', 'deal')",
            name=op.f("ck_custom_agent_runs_record_type_allowed"),
        ),
        sa.CheckConstraint(
            "action IN ('none', 'set_status', 'create_task')",
            name=op.f("ck_custom_agent_runs_action_allowed"),
        ),
        sa.CheckConstraint(
            "((mode = 'trial') = (outcome = 'shown')) AND "
            "((outcome = 'proposed') = (proposal_id IS NOT NULL))",
            name=op.f("ck_custom_agent_runs_mode_outcome_proposal_consistent"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "custom_agent_id", "version_no"],
            [
                "custom_agent_versions.tenant_id",
                "custom_agent_versions.custom_agent_id",
                "custom_agent_versions.version_no",
            ],
            name=op.f("fk_custom_agent_runs_agent_version"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_custom_agent_runs_tenant_id_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "proposal_id"],
            ["agent_actions.tenant_id", "agent_actions.id"],
            name=op.f("fk_custom_agent_runs_tenant_id_proposal_id_agent_actions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_custom_agent_runs_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_custom_agent_runs")),
    )
    op.create_index(
        "ix_custom_agent_runs_tenant_id_custom_agent_id",
        "custom_agent_runs",
        ["tenant_id", "custom_agent_id"],
    )
    op.create_index(
        "ix_custom_agent_runs_tenant_id_record_id", "custom_agent_runs", ["tenant_id", "record_id"]
    )
    op.execute("ALTER TABLE custom_agent_runs ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE custom_agent_runs FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY custom_agent_runs_tenant_isolation ON custom_agent_runs
            USING (tenant_id = crm_current_tenant())
            WITH CHECK (tenant_id = crm_current_tenant());
        """
    )
    op.execute(
        """
        CREATE FUNCTION custom_agent_runs_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'UPDATE' THEN
            RAISE EXCEPTION 'custom_agent_runs rows cannot be changed';
          END IF;
          IF OLD.created_at > now() - interval '365 days' THEN
            RAISE EXCEPTION 'custom_agent_runs rows can be deleted only after 365 days';
          END IF;
          RETURN OLD;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER custom_agent_runs_guard BEFORE UPDATE OR DELETE ON custom_agent_runs
            FOR EACH ROW EXECUTE FUNCTION custom_agent_runs_guard();
        """
    )
    op.execute(
        """
        DO $$
        DECLARE grantee_name text;
        BEGIN
          FOR grantee_name IN
            SELECT DISTINCT grantee FROM information_schema.role_table_grants
            WHERE table_schema = current_schema() AND table_name = 'custom_agent_runs'
              AND privilege_type IN ('UPDATE', 'TRUNCATE')
              AND grantee <> current_user
          LOOP
            EXECUTE format('REVOKE UPDATE, TRUNCATE ON custom_agent_runs FROM %I', grantee_name);
          END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS custom_agent_runs_guard ON custom_agent_runs;")
    op.execute("DROP FUNCTION IF EXISTS custom_agent_runs_guard();")
    op.execute("DROP POLICY IF EXISTS custom_agent_runs_tenant_isolation ON custom_agent_runs;")
    op.drop_index("ix_custom_agent_runs_tenant_id_record_id", table_name="custom_agent_runs")
    op.drop_index("ix_custom_agent_runs_tenant_id_custom_agent_id", table_name="custom_agent_runs")
    op.drop_table("custom_agent_runs")
