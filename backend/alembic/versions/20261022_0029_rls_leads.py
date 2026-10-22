"""Leads row-level security (0029).

Revision ID: 0029
Revises: 0028
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION crm_current_user() RETURNS uuid
        LANGUAGE sql STABLE
        AS $$ SELECT NULLIF(current_setting('app.user_id', true), '')::uuid $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION crm_lead_scope() RETURNS text
        LANGUAGE sql STABLE
        AS $$ SELECT NULLIF(current_setting('app.lead_scope', true), '') $$;
        """
    )
    op.execute("ALTER TABLE leads ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE leads FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY leads_tenant_scope ON leads
            USING (
                tenant_id = crm_current_tenant()
                AND (crm_lead_scope() = 'all' OR owner_id = crm_current_user())
            )
            WITH CHECK (
                tenant_id = crm_current_tenant()
                AND (crm_lead_scope() = 'all' OR owner_id = crm_current_user())
            );
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS leads_tenant_scope ON leads;")
    op.execute("ALTER TABLE leads NO FORCE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE leads DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP FUNCTION IF EXISTS crm_lead_scope();")
    op.execute("DROP FUNCTION IF EXISTS crm_current_user();")
