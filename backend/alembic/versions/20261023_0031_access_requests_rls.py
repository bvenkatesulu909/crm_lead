"""Signup before a principal exists + RLS on access_requests (ADR 0009).

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-23

Signup must check the latest request and insert a new one before app.tenant_id exists. crm_app
must not bypass RLS. Two narrow SECURITY DEFINER functions owned by crm_owner provide exactly
those operations: status returns only the latest status/tenant_id, submit inserts only when the
signup code belongs to an active tenant. Neither can list access requests. FORCE RLS then
protects all normal tenant-scoped reads/writes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION access_request_latest(p_issuer text, p_subject text)
        RETURNS TABLE (status text, tenant_id uuid)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT ar.status, ar.tenant_id
            FROM public.access_requests AS ar
            WHERE ar.idp_issuer = p_issuer AND ar.idp_subject = p_subject
            ORDER BY ar.created_at DESC
            LIMIT 1
        $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION access_request_submit(
            p_issuer text,
            p_subject text,
            p_email text,
            p_display_name text,
            p_code text
        )
        RETURNS TABLE (request_id uuid, tenant_id uuid)
        LANGUAGE sql
        VOLATILE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            INSERT INTO public.access_requests
                (tenant_id, idp_issuer, idp_subject, email, display_name)
            SELECT t.id, p_issuer, p_subject, p_email, p_display_name
            FROM public.tenants AS t
            WHERE t.signup_code = p_code
              AND t.status = 'active'
              AND p_issuer <> ''
              AND p_subject <> ''
              AND p_email <> ''
              AND p_display_name <> ''
              AND char_length(p_issuer) <= 255
              AND char_length(p_subject) <= 255
              AND char_length(p_email) <= 320
              AND char_length(p_display_name) <= 200
            RETURNING id, tenant_id
        $$;
        """
    )
    for function in (
        "access_request_latest(text, text)",
        "access_request_submit(text, text, text, text, text)",
    ):
        op.execute(f"ALTER FUNCTION {function} OWNER TO crm_owner;")
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC;")
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO crm_app;")
    op.execute(
        """
        COMMENT ON FUNCTION access_request_latest(text, text) IS
        'Latest signup request for one verified identity before app.tenant_id exists; returns '
        'only status and tenant_id, never a list.';
        """
    )
    op.execute(
        """
        COMMENT ON FUNCTION access_request_submit(text, text, text, text, text) IS
        'Insert-only signup before a principal exists. SECURITY DEFINER is required because '
        'crm_app must not bypass RLS; validates the active tenant signup code and input lengths.';
        """
    )

    op.execute("ALTER TABLE access_requests ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE access_requests FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY access_requests_tenant_isolation ON access_requests
            USING (tenant_id = crm_current_tenant())
            WITH CHECK (tenant_id = crm_current_tenant());
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS access_requests_tenant_isolation ON access_requests;")
    op.execute("ALTER TABLE access_requests NO FORCE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE access_requests DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP FUNCTION IF EXISTS access_request_submit(text, text, text, text, text);")
    op.execute("DROP FUNCTION IF EXISTS access_request_latest(text, text);")
