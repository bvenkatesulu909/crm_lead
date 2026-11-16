"""Custom agents of the no-code builder (ADR 0034, AB1).

Revision ID: 0068
Revises: 0067
Create Date: 2026-11-16

Two new tables. ``custom_agents`` names an agent and points at its newest version.
``custom_agent_versions`` holds what the agent does: the purpose, the instruction, the read sets and
the suggestion kinds it may use. ENABLE + FORCE row-level security and the tenant policy on both
(ADR 0009). The version table is insert-only: a trigger refuses every UPDATE and a DELETE of a row
younger than 365 days, and the application role loses UPDATE and TRUNCATE on it.

The two menus (read sets and suggestion kinds) are written out here on purpose: a migration must not
change when the code does, and the database refuses anything that is not on the menu.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0068"
down_revision: str | None = "0067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

READ_SETS = (
    "ARRAY['lead', 'lead_activity', 'account', 'account_health', 'deal', 'deal_quotes']::text[]"
)
KINDS = "ARRAY['lead.set_status', 'lead.assign', 'activity.create_task']::text[]"


def _tenant_policy(table: str) -> None:
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
        "custom_agents",
        sa.Column("agent_key", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
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
            "agent_key ~ '^custom_[0-9a-f]{12}$'", name=op.f("ck_custom_agents_key_format")
        ),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 60", name=op.f("ck_custom_agents_name_length")
        ),
        sa.CheckConstraint("current_version >= 1", name=op.f("ck_custom_agents_version_positive")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_custom_agents_tenant_id_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_custom_agents_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_custom_agents")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_custom_agents_tenant_id_id")),
        sa.UniqueConstraint(
            "tenant_id", "agent_key", name=op.f("uq_custom_agents_tenant_id_agent_key")
        ),
    )
    _tenant_policy("custom_agents")

    op.create_table(
        "custom_agent_versions",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("custom_agent_id", sa.Uuid(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=200), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("read_sets", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("suggestion_kinds", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("cleaned", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "version_no >= 1", name=op.f("ck_custom_agent_versions_version_positive")
        ),
        sa.CheckConstraint(
            "char_length(purpose) BETWEEN 1 AND 200",
            name=op.f("ck_custom_agent_versions_purpose_length"),
        ),
        sa.CheckConstraint(
            "char_length(instruction) BETWEEN 1 AND 4000",
            name=op.f("ck_custom_agent_versions_instruction_length"),
        ),
        sa.CheckConstraint(
            f"cardinality(read_sets) BETWEEN 1 AND 3 AND read_sets <@ {READ_SETS}",
            name=op.f("ck_custom_agent_versions_read_sets_allowed"),
        ),
        sa.CheckConstraint(
            f"cardinality(suggestion_kinds) BETWEEN 1 AND 2 AND suggestion_kinds <@ {KINDS}",
            name=op.f("ck_custom_agent_versions_suggestion_kinds_allowed"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(cleaned) = 'array'",
            name=op.f("ck_custom_agent_versions_cleaned_is_list"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "custom_agent_id"],
            ["custom_agents.tenant_id", "custom_agents.id"],
            name=op.f("fk_custom_agent_versions_tenant_id_custom_agent_id_custom_agents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_custom_agent_versions_tenant_id_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_custom_agent_versions_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_custom_agent_versions")),
        sa.UniqueConstraint(
            "tenant_id",
            "custom_agent_id",
            "version_no",
            name=op.f("uq_custom_agent_versions_tenant_id_custom_agent_id_version_no"),
        ),
    )
    op.create_index(
        "ix_custom_agent_versions_tenant_id_custom_agent_id",
        "custom_agent_versions",
        ["tenant_id", "custom_agent_id"],
    )
    _tenant_policy("custom_agent_versions")
    op.execute(
        """
        CREATE FUNCTION custom_agent_versions_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'UPDATE' THEN
            RAISE EXCEPTION 'custom_agent_versions rows cannot be changed';
          END IF;
          IF OLD.created_at > now() - interval '365 days' THEN
            RAISE EXCEPTION 'custom_agent_versions rows can be deleted only after 365 days';
          END IF;
          RETURN OLD;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER custom_agent_versions_guard BEFORE UPDATE OR DELETE
            ON custom_agent_versions
            FOR EACH ROW EXECUTE FUNCTION custom_agent_versions_guard();
        """
    )
    op.execute(
        """
        DO $$
        DECLARE grantee_name text;
        BEGIN
          FOR grantee_name IN
            SELECT DISTINCT grantee FROM information_schema.role_table_grants
            WHERE table_schema = current_schema() AND table_name = 'custom_agent_versions'
              AND privilege_type IN ('UPDATE', 'TRUNCATE')
              AND grantee <> current_user
          LOOP
            EXECUTE format(
                'REVOKE UPDATE, TRUNCATE ON custom_agent_versions FROM %I', grantee_name
            );
          END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS custom_agent_versions_guard ON custom_agent_versions;")
    op.execute("DROP FUNCTION IF EXISTS custom_agent_versions_guard();")
    op.execute(
        "DROP POLICY IF EXISTS custom_agent_versions_tenant_isolation ON custom_agent_versions;"
    )
    op.drop_index(
        "ix_custom_agent_versions_tenant_id_custom_agent_id", table_name="custom_agent_versions"
    )
    op.drop_table("custom_agent_versions")
    op.execute("DROP POLICY IF EXISTS custom_agents_tenant_isolation ON custom_agents;")
    op.drop_table("custom_agents")
