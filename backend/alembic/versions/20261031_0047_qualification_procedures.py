"""Qualification procedures (QA1, docs/qualifier.md).

Revision ID: 0047
Revises: 0046
Create Date: 2026-10-31

One table, ``qualification_procedures``: the organisation's written steps, one row per version,
at most one active. ENABLE + FORCE row-level security and the one tenant policy (ADR 0009).
History is kept: a trigger lets an UPDATE do exactly one thing (retire an active version) and
refuses every DELETE, and the application role has no DELETE or TRUNCATE privilege either.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "qualification_procedures"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("steps", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "cleaned",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
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
            "version >= 1", name=op.f("ck_qualification_procedures_version_positive")
        ),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 100",
            name=op.f("ck_qualification_procedures_name_length"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(steps) = 'array' AND jsonb_array_length(steps) BETWEEN 1 AND 20",
            name=op.f("ck_qualification_procedures_steps_count"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(cleaned) = 'array'",
            name=op.f("ck_qualification_procedures_cleaned_is_list"),
        ),
        sa.CheckConstraint(
            "(active) = (retired_at IS NULL)",
            name=op.f("ck_qualification_procedures_retired_means_inactive"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_qualification_procedures_tenant_id_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_qualification_procedures_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_qualification_procedures")),
        sa.UniqueConstraint(
            "tenant_id", "version", name=op.f("uq_qualification_procedures_tenant_id_version")
        ),
    )
    op.create_index(
        "uq_qualification_procedures_one_active",
        TABLE,
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("active"),
    )

    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY {TABLE}_tenant_isolation ON {TABLE}
            USING (tenant_id = crm_current_tenant())
            WITH CHECK (tenant_id = crm_current_tenant());
        """
    )
    # Lock 1 (the trigger binds every role): the only change a row may ever get is active ->
    # false together with a retired_at; no DELETE at all.
    op.execute(
        f"""
        CREATE FUNCTION {TABLE}_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION '{TABLE} rows cannot be deleted';
          END IF;
          IF OLD.active IS NOT TRUE OR NEW.active IS NOT FALSE THEN
            RAISE EXCEPTION 'a qualification procedure can only be retired';
          END IF;
          IF (NEW.id, NEW.tenant_id, NEW.version, NEW.name, NEW.steps, NEW.cleaned,
              NEW.created_by_user_id, NEW.created_at)
             IS DISTINCT FROM
             (OLD.id, OLD.tenant_id, OLD.version, OLD.name, OLD.steps, OLD.cleaned,
              OLD.created_by_user_id, OLD.created_at) THEN
            RAISE EXCEPTION 'a retired qualification procedure keeps its text';
          END IF;
          RETURN NEW;
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
    # Lock 2: the application role may not delete or truncate.
    op.execute(
        f"""
        DO $$
        DECLARE grantee_name text;
        BEGIN
          FOR grantee_name IN
            SELECT DISTINCT grantee FROM information_schema.role_table_grants
            WHERE table_schema = current_schema() AND table_name = '{TABLE}'
              AND privilege_type IN ('DELETE', 'TRUNCATE')
              AND grantee <> current_user
          LOOP
            EXECUTE format('REVOKE DELETE, TRUNCATE ON {TABLE} FROM %I', grantee_name);
          END LOOP;
        END $$;
        """  # noqa: S608 - TABLE is a constant of this file, not input
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {TABLE}_guard ON {TABLE};")
    op.execute(f"DROP FUNCTION IF EXISTS {TABLE}_guard();")
    op.execute(f"DROP POLICY IF EXISTS {TABLE}_tenant_isolation ON {TABLE};")
    op.drop_index("uq_qualification_procedures_one_active", table_name=TABLE)
    op.drop_table(TABLE)
