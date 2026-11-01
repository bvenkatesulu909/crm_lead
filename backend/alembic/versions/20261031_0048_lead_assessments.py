"""What the Qualifier concluded about a lead (QA2, docs/qualifier.md).

Revision ID: 0048
Revises: 0047
Create Date: 2026-10-31

* ``lead_assessments``: one insert-only row per assessment (forced row-level security, ADR 0009;
  a trigger refuses every UPDATE and DELETE and the application role has neither privilege).
* ``qualification_procedures`` gets a unique ``(tenant_id, id)`` so an assessment can point at
  its procedure with a composite foreign key that keeps the organisation consistent.
* ``agent_actions.agent`` may now also be ``qualifier``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "lead_assessments"
AGENT_CHECK = "ck_agent_actions_agent_allowed"


def upgrade() -> None:
    op.create_unique_constraint(
        op.f("uq_qualification_procedures_tenant_id_id"),
        "qualification_procedures",
        ["tenant_id", "id"],
    )
    op.drop_constraint(op.f(AGENT_CHECK), "agent_actions", type_="check")
    op.create_check_constraint(
        op.f(AGENT_CHECK),
        "agent_actions",
        "agent IN ('staff_assistant', 'mcp_client', 'qualifier')",
    )

    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        TABLE,
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("procedure_id", sa.Uuid(), nullable=False),
        sa.Column("procedure_version", sa.Integer(), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("matched_steps", jsonb, nullable=False),
        sa.Column("reasons", jsonb, nullable=False),
        sa.Column("missing", jsonb, nullable=False),
        sa.Column("fields_given", jsonb, nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "decision IN ('qualify', 'unqualify', 'contact_first', 'need_info', 'no_change')",
            name=op.f("ck_lead_assessments_decision_allowed"),
        ),
        sa.CheckConstraint(
            "outcome IN ('proposed', 'no_proposal', 'blocked')",
            name=op.f("ck_lead_assessments_outcome_allowed"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(matched_steps) = 'array' AND jsonb_typeof(reasons) = 'array' "
            "AND jsonb_typeof(missing) = 'array' AND jsonb_typeof(fields_given) = 'array'",
            name=op.f("ck_lead_assessments_lists_are_arrays"),
        ),
        sa.CheckConstraint(
            "(outcome = 'proposed') = (proposal_id IS NOT NULL)",
            name=op.f("ck_lead_assessments_proposal_link"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "lead_id"],
            ["leads.tenant_id", "leads.id"],
            name=op.f("fk_lead_assessments_tenant_id_lead_id_leads"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "procedure_id"],
            ["qualification_procedures.tenant_id", "qualification_procedures.id"],
            name=op.f("fk_lead_assessments_tenant_id_procedure_id_qualification_procedures"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "requested_by_user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_lead_assessments_tenant_id_requested_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["agent_actions.id"],
            name=op.f("fk_lead_assessments_proposal_id_agent_actions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_lead_assessments_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lead_assessments")),
    )
    op.create_index("ix_lead_assessments_tenant_id_lead_id", TABLE, ["tenant_id", "lead_id", "seq"])

    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY {TABLE}_tenant_isolation ON {TABLE}
            USING (tenant_id = crm_current_tenant())
            WITH CHECK (tenant_id = crm_current_tenant());
        """
    )
    # Lock 1: the trigger binds every role, the table's owner included.
    op.execute(
        f"""
        CREATE FUNCTION {TABLE}_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION '{TABLE} rows cannot be changed or deleted';
        END
        $$;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {TABLE}_guard BEFORE UPDATE OR DELETE ON {TABLE}
            FOR EACH ROW EXECUTE FUNCTION {TABLE}_guard();
        """
    )
    # Lock 2: the application role has no UPDATE, DELETE or TRUNCATE privilege at all.
    op.execute(
        f"""
        DO $$
        DECLARE grantee_name text;
        BEGIN
          FOR grantee_name IN
            SELECT DISTINCT grantee FROM information_schema.role_table_grants
            WHERE table_schema = current_schema() AND table_name = '{TABLE}'
              AND privilege_type IN ('UPDATE', 'DELETE', 'TRUNCATE')
              AND grantee <> current_user
          LOOP
            EXECUTE format('REVOKE UPDATE, DELETE, TRUNCATE ON {TABLE} FROM %I', grantee_name);
          END LOOP;
        END $$;
        """  # noqa: S608 - TABLE is a constant of this file, not input
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {TABLE}_guard ON {TABLE};")
    op.execute(f"DROP FUNCTION IF EXISTS {TABLE}_guard();")
    op.execute(f"DROP POLICY IF EXISTS {TABLE}_tenant_isolation ON {TABLE};")
    op.drop_index("ix_lead_assessments_tenant_id_lead_id", table_name=TABLE)
    op.drop_table(TABLE)
    op.drop_constraint(op.f(AGENT_CHECK), "agent_actions", type_="check")
    op.create_check_constraint(
        op.f(AGENT_CHECK), "agent_actions", "agent IN ('staff_assistant', 'mcp_client')"
    )
    op.drop_constraint(
        op.f("uq_qualification_procedures_tenant_id_id"), "qualification_procedures", type_="unique"
    )
