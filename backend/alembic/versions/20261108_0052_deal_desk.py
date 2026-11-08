"""Deal desk: stored reviews, deals as an approval target, the deal desk as an author (DD2)

Revision ID: 0052
Revises: 0051
Create Date: 2026-11-08

ADR 0024. One new table, ``deal_reviews``: ENABLE + FORCE row-level security and the tenant
policy (ADR 0009), plus the same two locks as ``web_evidence`` (a trigger refuses every UPDATE and
a DELETE of a row younger than 365 days; the application role loses UPDATE and TRUNCATE). The
approval queue learns two names: the record type ``opportunity`` (a follow-up task on a deal) and
the author ``deal_desk``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0052"
down_revision: str | None = "0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AGENT_CHECK = "ck_agent_actions_agent_allowed"
TARGET_CHECK = "ck_agent_actions_target_type_allowed"


def upgrade() -> None:
    op.create_table(
        "deal_reviews",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("brief", sa.Text(), nullable=False),
        sa.Column(
            "findings",
            sa.dialects.postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "reviewers",
            sa.dialects.postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "proposal_ids",
            sa.dialects.postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("input_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "char_length(brief) BETWEEN 1 AND 1200", name=op.f("ck_deal_reviews_brief_length")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(findings) = 'array'", name=op.f("ck_deal_reviews_findings_is_list")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(reviewers) = 'object'", name=op.f("ck_deal_reviews_reviewers_is_object")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(proposal_ids) = 'array'",
            name=op.f("ck_deal_reviews_proposal_ids_is_list"),
        ),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0",
            name=op.f("ck_deal_reviews_tokens_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "opportunity_id"],
            ["opportunities.tenant_id", "opportunities.id"],
            name=op.f("fk_deal_reviews_tenant_id_opportunity_id_opportunities"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "requested_by_user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_deal_reviews_tenant_id_requested_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_deal_reviews_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deal_reviews")),
    )
    op.create_index(
        "ix_deal_reviews_tenant_id_opportunity_id",
        "deal_reviews",
        ["tenant_id", "opportunity_id", "seq"],
    )

    op.execute("ALTER TABLE deal_reviews ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE deal_reviews FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY deal_reviews_tenant_isolation ON deal_reviews
            USING (tenant_id = crm_current_tenant())
            WITH CHECK (tenant_id = crm_current_tenant());
        """
    )
    # Lock 1: the trigger, which binds every role including the table's owner.
    op.execute(
        """
        CREATE FUNCTION deal_reviews_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'UPDATE' THEN
            RAISE EXCEPTION 'deal_reviews rows cannot be changed';
          END IF;
          IF OLD.created_at > now() - interval '365 days' THEN
            RAISE EXCEPTION 'deal_reviews rows can be deleted only after 365 days';
          END IF;
          RETURN OLD;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER deal_reviews_guard BEFORE UPDATE OR DELETE ON deal_reviews
            FOR EACH ROW EXECUTE FUNCTION deal_reviews_guard();
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
            WHERE table_schema = current_schema() AND table_name = 'deal_reviews'
              AND privilege_type IN ('UPDATE', 'TRUNCATE')
              AND grantee <> current_user
          LOOP
            EXECUTE format('REVOKE UPDATE, TRUNCATE ON deal_reviews FROM %I', grantee_name);
          END LOOP;
        END $$;
        """
    )

    op.drop_constraint(op.f(AGENT_CHECK), "agent_actions", type_="check")
    op.create_check_constraint(
        op.f(AGENT_CHECK),
        "agent_actions",
        "agent IN ('staff_assistant', 'mcp_client', 'qualifier', 'lead_agent', 'deal_desk')",
    )
    op.drop_constraint(op.f(TARGET_CHECK), "agent_actions", type_="check")
    op.create_check_constraint(
        op.f(TARGET_CHECK),
        "agent_actions",
        "target_type IN ('lead', 'account', 'contact', 'opportunity')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f(TARGET_CHECK), "agent_actions", type_="check")
    op.create_check_constraint(
        op.f(TARGET_CHECK), "agent_actions", "target_type IN ('lead', 'account', 'contact')"
    )
    op.drop_constraint(op.f(AGENT_CHECK), "agent_actions", type_="check")
    op.create_check_constraint(
        op.f(AGENT_CHECK),
        "agent_actions",
        "agent IN ('staff_assistant', 'mcp_client', 'qualifier', 'lead_agent')",
    )
    op.execute("DROP TRIGGER IF EXISTS deal_reviews_guard ON deal_reviews;")
    op.execute("DROP FUNCTION IF EXISTS deal_reviews_guard();")
    op.execute("DROP POLICY IF EXISTS deal_reviews_tenant_isolation ON deal_reviews;")
    op.drop_index("ix_deal_reviews_tenant_id_opportunity_id", table_name="deal_reviews")
    op.drop_table("deal_reviews")
