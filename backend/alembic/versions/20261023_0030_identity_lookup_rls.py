"""Identity lookup before the tenant is known + RLS on users (ADR 0009).

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-23

Login must find a user by (issuer, subject) before app.tenant_id exists. crm_app must not
bypass RLS, so this one narrow SECURITY DEFINER function owned by crm_owner performs exactly
that lookup and returns only id/tenant_id/is_active. The normal User row is then loaded after
bind_tenant(), which enables FORCE RLS on users.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTION = "identity_lookup_user(text, text)"


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION identity_lookup_user(p_issuer text, p_subject text)
        RETURNS TABLE (user_id uuid, tenant_id uuid, is_active boolean)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT u.id, u.tenant_id, u.is_active
            FROM public.users AS u
            WHERE u.idp_issuer = p_issuer AND u.idp_subject = p_subject
        $$;
        """
    )
    op.execute("ALTER FUNCTION identity_lookup_user(text, text) OWNER TO crm_owner;")
    op.execute("REVOKE ALL ON FUNCTION identity_lookup_user(text, text) FROM PUBLIC;")
    op.execute("GRANT EXECUTE ON FUNCTION identity_lookup_user(text, text) TO crm_app;")
    op.execute(
        """
        COMMENT ON FUNCTION identity_lookup_user(text, text) IS
        'Narrow login lookup before app.tenant_id exists. SECURITY DEFINER is required because '
        'crm_app must not bypass FORCE RLS on users; returns only id, tenant_id and is_active.';
        """
    )

    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY users_tenant_isolation ON users
            USING (tenant_id = crm_current_tenant())
            WITH CHECK (tenant_id = crm_current_tenant());
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS users_tenant_isolation ON users;")
    op.execute("ALTER TABLE users NO FORCE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE users DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP FUNCTION IF EXISTS identity_lookup_user(text, text);")
