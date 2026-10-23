"""Aggregate operational counts for /metrics under RLS (ADR 0009).

Revision ID: 0036
Revises: 0035
Create Date: 2026-10-23

The metrics scrape has no tenant. With RLS on outbox_jobs, kb_documents and kb_chunks its
counts were silently zero. ops_queue_counts() is a narrow SECURITY DEFINER exception: it
returns only (metric, status, total) aggregates across tenants - no ids, no tenant ids, no row
contents - with a fixed search_path and EXECUTE only for crm_app.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ops_queue_counts()
        RETURNS TABLE (metric text, status text, total bigint)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT 'outbox_jobs', j.status::text, count(*)
            FROM public.outbox_jobs AS j
            GROUP BY j.status
            UNION ALL
            SELECT 'kb_documents', d.status::text, count(*)
            FROM public.kb_documents AS d
            GROUP BY d.status
            UNION ALL
            SELECT 'kb_chunks_missing_embedding', NULL, count(*)
            FROM public.kb_chunks AS c
            WHERE c.embedding IS NULL
        $$;
        """
    )
    op.execute("ALTER FUNCTION ops_queue_counts() OWNER TO crm_owner;")
    op.execute("REVOKE ALL ON FUNCTION ops_queue_counts() FROM PUBLIC;")
    op.execute("GRANT EXECUTE ON FUNCTION ops_queue_counts() TO crm_app;")
    op.execute(
        """
        COMMENT ON FUNCTION ops_queue_counts() IS
        'Cross-tenant aggregate counts for the metrics scrape only (no tenant context). '
        'Returns counts per status, never ids or row contents.';
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS ops_queue_counts();")
