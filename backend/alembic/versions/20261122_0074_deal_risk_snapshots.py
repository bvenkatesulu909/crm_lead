"""Deal risk forecast: insert-only snapshots (DR2)

Revision ID: 0074
Revises: 0073
Create Date: 2026-11-22

ADR 0037. One new table, ``deal_risk_snapshots``: ENABLE + FORCE row-level security and the
tenant policy (ADR 0009), plus the same two locks as ``deal_reviews`` (a trigger refuses every
UPDATE and a DELETE of a row younger than 365 days; the application role loses UPDATE and
TRUNCATE). The level, the score range and the shape of the JSON columns are database checks.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0074"
down_revision: str | None = "0073"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "deal_risk_snapshots",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("level", sa.String(length=10), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("rules_version", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=12), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "factors",
            sa.dialects.postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "unknown",
            sa.dialects.postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "level IN ('low', 'medium', 'high')", name=op.f("ck_deal_risk_snapshots_level_allowed")
        ),
        sa.CheckConstraint(
            "score BETWEEN 0 AND 100", name=op.f("ck_deal_risk_snapshots_score_range")
        ),
        sa.CheckConstraint(
            "rules_version >= 1", name=op.f("ck_deal_risk_snapshots_rules_version_positive")
        ),
        sa.CheckConstraint(
            "source IN ('nightly', 'on_demand')", name=op.f("ck_deal_risk_snapshots_source_allowed")
        ),
        # A nightly snapshot has no asker; an on-demand one always has.
        sa.CheckConstraint(
            "(source = 'nightly') = (requested_by_user_id IS NULL)",
            name=op.f("ck_deal_risk_snapshots_asker_matches_source"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(factors) = 'array'", name=op.f("ck_deal_risk_snapshots_factors_is_list")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(unknown) = 'array'", name=op.f("ck_deal_risk_snapshots_unknown_is_list")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "opportunity_id"],
            ["opportunities.tenant_id", "opportunities.id"],
            name=op.f("fk_deal_risk_snapshots_tenant_id_opportunity_id_opportunities"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "requested_by_user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_deal_risk_snapshots_tenant_id_requested_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_deal_risk_snapshots_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deal_risk_snapshots")),
    )
    op.create_index(
        "ix_deal_risk_snapshots_tenant_id_opportunity_id",
        "deal_risk_snapshots",
        ["tenant_id", "opportunity_id", "seq"],
    )
    op.create_index(
        "ix_deal_risk_snapshots_tenant_id_created_at",
        "deal_risk_snapshots",
        ["tenant_id", "created_at"],
    )

    op.execute("ALTER TABLE deal_risk_snapshots ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE deal_risk_snapshots FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY deal_risk_snapshots_tenant_isolation ON deal_risk_snapshots
            USING (tenant_id = crm_current_tenant())
            WITH CHECK (tenant_id = crm_current_tenant());
        """
    )
    # Lock 1: the trigger, which binds every role including the table's owner.
    op.execute(
        """
        CREATE FUNCTION deal_risk_snapshots_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'UPDATE' THEN
            RAISE EXCEPTION 'deal_risk_snapshots rows cannot be changed';
          END IF;
          IF OLD.created_at > now() - interval '365 days' THEN
            RAISE EXCEPTION 'deal_risk_snapshots rows can be deleted only after 365 days';
          END IF;
          RETURN OLD;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER deal_risk_snapshots_guard BEFORE UPDATE OR DELETE ON deal_risk_snapshots
            FOR EACH ROW EXECUTE FUNCTION deal_risk_snapshots_guard();
        """
    )
    # Lock 2: the application role has no UPDATE or TRUNCATE privilege at all.
    op.execute(
        """
        DO $$
        DECLARE grantee_name text;
        BEGIN
          FOR grantee_name IN
            SELECT DISTINCT grantee FROM information_schema.role_table_grants
            WHERE table_schema = current_schema() AND table_name = 'deal_risk_snapshots'
              AND privilege_type IN ('UPDATE', 'TRUNCATE')
              AND grantee <> current_user
          LOOP
            EXECUTE format('REVOKE UPDATE, TRUNCATE ON deal_risk_snapshots FROM %I', grantee_name);
          END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS deal_risk_snapshots_guard ON deal_risk_snapshots;")
    op.execute("DROP FUNCTION IF EXISTS deal_risk_snapshots_guard();")
    op.execute("DROP POLICY IF EXISTS deal_risk_snapshots_tenant_isolation ON deal_risk_snapshots;")
    op.drop_index("ix_deal_risk_snapshots_tenant_id_created_at", table_name="deal_risk_snapshots")
    op.drop_index(
        "ix_deal_risk_snapshots_tenant_id_opportunity_id", table_name="deal_risk_snapshots"
    )
    op.drop_table("deal_risk_snapshots")
