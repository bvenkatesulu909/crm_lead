"""Approved "why this proposal" texts for proposal decks; quotes and the deck writer in the approval
queue (ADR 0032 Amendment A, PD7)

Revision ID: 0066
Revises: 0065
Create Date: 2026-11-14

One new table, ``deck_summaries``: the text a person approved for a quote's deck. ENABLE + FORCE
row-level security and the tenant policy (ADR 0009), plus the two locks the other insert-only tables
have (a trigger refuses every UPDATE and a DELETE of a row younger than 365 days; the application
role loses UPDATE and TRUNCATE). The approval queue learns two names: the record type ``quote`` (a
summary slide for a quote's deck) and the author ``deck_writer``.

The name lists are written out here on purpose: a migration must not change when the code does.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0066"
down_revision: str | None = "0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AGENT_CHECK = "ck_agent_actions_agent_allowed"
TARGET_CHECK = "ck_agent_actions_target_type_allowed"


def upgrade() -> None:
    op.create_table(
        "deck_summaries",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("quote_id", sa.Uuid(), nullable=False),
        sa.Column("approved_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "char_length(body) BETWEEN 1 AND 1000", name=op.f("ck_deck_summaries_body_length")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "quote_id"],
            ["quotes.tenant_id", "quotes.id"],
            name=op.f("fk_deck_summaries_tenant_id_quote_id_quotes"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "approved_by_user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_deck_summaries_tenant_id_approved_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "proposal_id"],
            ["agent_actions.tenant_id", "agent_actions.id"],
            name=op.f("fk_deck_summaries_tenant_id_proposal_id_agent_actions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_deck_summaries_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deck_summaries")),
    )
    op.create_index(
        "ix_deck_summaries_tenant_id_quote_id", "deck_summaries", ["tenant_id", "quote_id", "seq"]
    )

    op.execute("ALTER TABLE deck_summaries ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE deck_summaries FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY deck_summaries_tenant_isolation ON deck_summaries
            USING (tenant_id = crm_current_tenant())
            WITH CHECK (tenant_id = crm_current_tenant());
        """
    )
    op.execute(
        """
        CREATE FUNCTION deck_summaries_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'UPDATE' THEN
            RAISE EXCEPTION 'deck_summaries rows cannot be changed';
          END IF;
          IF OLD.created_at > now() - interval '365 days' THEN
            RAISE EXCEPTION 'deck_summaries rows can be deleted only after 365 days';
          END IF;
          RETURN OLD;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER deck_summaries_guard BEFORE UPDATE OR DELETE ON deck_summaries
            FOR EACH ROW EXECUTE FUNCTION deck_summaries_guard();
        """
    )
    op.execute(
        """
        DO $$
        DECLARE grantee_name text;
        BEGIN
          FOR grantee_name IN
            SELECT DISTINCT grantee FROM information_schema.role_table_grants
            WHERE table_schema = current_schema() AND table_name = 'deck_summaries'
              AND privilege_type IN ('UPDATE', 'TRUNCATE')
              AND grantee <> current_user
          LOOP
            EXECUTE format('REVOKE UPDATE, TRUNCATE ON deck_summaries FROM %I', grantee_name);
          END LOOP;
        END $$;
        """
    )

    op.drop_constraint(op.f(AGENT_CHECK), "agent_actions", type_="check")
    op.create_check_constraint(
        op.f(AGENT_CHECK),
        "agent_actions",
        "agent IN ('staff_assistant', 'mcp_client', 'qualifier', 'lead_agent', 'deal_desk', "
        "'deck_writer')",
    )
    op.drop_constraint(op.f(TARGET_CHECK), "agent_actions", type_="check")
    op.create_check_constraint(
        op.f(TARGET_CHECK),
        "agent_actions",
        "target_type IN ('lead', 'account', 'contact', 'opportunity', 'quote')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM agent_actions WHERE agent = 'deck_writer' OR target_type = 'quote'")
    op.drop_constraint(op.f(TARGET_CHECK), "agent_actions", type_="check")
    op.create_check_constraint(
        op.f(TARGET_CHECK),
        "agent_actions",
        "target_type IN ('lead', 'account', 'contact', 'opportunity')",
    )
    op.drop_constraint(op.f(AGENT_CHECK), "agent_actions", type_="check")
    op.create_check_constraint(
        op.f(AGENT_CHECK),
        "agent_actions",
        "agent IN ('staff_assistant', 'mcp_client', 'qualifier', 'lead_agent', 'deal_desk')",
    )
    op.execute("DROP TRIGGER IF EXISTS deck_summaries_guard ON deck_summaries;")
    op.execute("DROP FUNCTION IF EXISTS deck_summaries_guard();")
    op.execute("DROP POLICY IF EXISTS deck_summaries_tenant_isolation ON deck_summaries;")
    op.drop_index("ix_deck_summaries_tenant_id_quote_id", table_name="deck_summaries")
    op.drop_table("deck_summaries")
