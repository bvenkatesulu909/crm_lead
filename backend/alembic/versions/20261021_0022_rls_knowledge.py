"""Row-Level Security, first domain: knowledge tables (ADR 0009, staged rollout).

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-21

Creates crm_current_tenant() (reads app.tenant_id, fail-closed when unset) and enables FORCE
Row-Level Security with a tenant-isolation policy on kb_documents and kb_chunks. Other domains
follow in later migrations; tenants and signup_code_attempts are intentionally outside RLS
(no tenant column / identity-scoped - see ADR 0009).
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("kb_documents", "kb_chunks")


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION crm_current_tenant() RETURNS uuid
        LANGUAGE sql STABLE
        AS $$
            SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid
        $$;
        """
    )
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
                USING (tenant_id = crm_current_tenant())
                WITH CHECK (tenant_id = crm_current_tenant());
            """
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP FUNCTION IF EXISTS crm_current_tenant();")
