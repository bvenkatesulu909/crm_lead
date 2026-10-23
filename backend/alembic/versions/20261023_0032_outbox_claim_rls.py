"""Worker claims outbox jobs across tenants + RLS on outbox_jobs (ADR 0009).

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-23

The worker must find a due job before knowing its tenant. crm_app cannot bypass RLS, so the
SECURITY DEFINER function outbox_claim() performs one atomic FOR UPDATE SKIP LOCKED claim and
returns only that job. The worker then binds app.tenant_id to job.tenant_id before the handler.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION outbox_claim(p_now timestamptz, p_stale_before timestamptz)
        RETURNS TABLE (
            job_id uuid,
            tenant_id uuid,
            kind text,
            payload jsonb,
            attempts integer
        )
        LANGUAGE sql
        VOLATILE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            WITH candidate AS (
                SELECT j.id
                FROM public.outbox_jobs AS j
                WHERE (j.status = 'pending' AND j.run_after <= p_now)
                   OR (j.status = 'running' AND j.locked_at < p_stale_before)
                ORDER BY j.run_after
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE public.outbox_jobs AS j
            SET status = 'running',
                attempts = j.attempts + 1,
                locked_at = p_now
            FROM candidate AS c
            WHERE j.id = c.id
            RETURNING j.id, j.tenant_id, j.kind, j.payload, j.attempts
        $$;
        """
    )
    op.execute("ALTER FUNCTION outbox_claim(timestamptz, timestamptz) OWNER TO crm_owner;")
    op.execute("REVOKE ALL ON FUNCTION outbox_claim(timestamptz, timestamptz) FROM PUBLIC;")
    op.execute("GRANT EXECUTE ON FUNCTION outbox_claim(timestamptz, timestamptz) TO crm_app;")
    op.execute(
        """
        COMMENT ON FUNCTION outbox_claim(timestamptz, timestamptz) IS
        'Atomic cross-tenant worker claim before app.tenant_id exists. SECURITY DEFINER is '
        'required because crm_app must not bypass RLS; returns only the claimed job.';
        """
    )

    op.execute("ALTER TABLE outbox_jobs ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE outbox_jobs FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY outbox_jobs_tenant_isolation ON outbox_jobs
            USING (tenant_id = crm_current_tenant())
            WITH CHECK (tenant_id = crm_current_tenant());
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS outbox_jobs_tenant_isolation ON outbox_jobs;")
    op.execute("ALTER TABLE outbox_jobs NO FORCE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE outbox_jobs DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP FUNCTION IF EXISTS outbox_claim(timestamptz, timestamptz);")
