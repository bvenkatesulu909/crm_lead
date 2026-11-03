"""Anonymous daily counters of the website chat (docs/pilot-report.md, step PR1).

Revision ID: 0049
Revises: 0048
Create Date: 2026-11-03

* ``public_chat_daily_stats``: two numbers per organisation and UTC day - conversations started and
  leads saved. Nothing that could identify a visitor, a message or a lead. Forced row-level security
  (ADR 0009).
* Two locks keep the numbers honest, as for the insert-only tables: a trigger that refuses any
  UPDATE that would LOWER a counter, and no DELETE or TRUNCATE privilege for the application role.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "public_chat_daily_stats"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column(
            "conversations_started", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("leads_saved", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "conversations_started >= 0 AND leads_saved >= 0",
            name=op.f("ck_public_chat_daily_stats_counts_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_public_chat_daily_stats_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "day", name=op.f("pk_public_chat_daily_stats")),
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
    # Lock 1: a counter can only grow. The trigger binds every role, the table's owner included.
    op.execute(
        f"""
        CREATE FUNCTION {TABLE}_only_grow() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.conversations_started < OLD.conversations_started
             OR NEW.leads_saved < OLD.leads_saved THEN
            RAISE EXCEPTION '{TABLE} counters can only grow';
          END IF;
          RETURN NEW;
        END
        $$;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {TABLE}_only_grow BEFORE UPDATE ON {TABLE}
            FOR EACH ROW EXECUTE FUNCTION {TABLE}_only_grow();
        """
    )
    # Lock 2: the application role may add and raise, never delete or empty the table.
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
    op.execute(f"DROP TRIGGER IF EXISTS {TABLE}_only_grow ON {TABLE};")
    op.execute(f"DROP FUNCTION IF EXISTS {TABLE}_only_grow();")
    op.execute(f"DROP POLICY IF EXISTS {TABLE}_tenant_isolation ON {TABLE};")
    op.drop_table(TABLE)
