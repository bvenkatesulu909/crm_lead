"""Tenant-isolation RLS on sales, quotes, orders and billing (ADR 0009, step 5).

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-23

Pipeline, catalogue, quotes, orders, invoices, credit notes, payments and number counters.
Each table gets ENABLE + FORCE row-level security and one policy with the same expression for
USING and WITH CHECK: tenant_id = crm_current_tenant(). An unset app.tenant_id gives no rows and
rejects inserts (fail closed). Record-level rules (owner, portal grants) stay in the application
policies; RLS is the second layer that a forgotten tenant filter cannot get past.

The table names are fixed identifiers below, never input. Rollback is the downgrade (or the
documented owner-run DISABLE ROW LEVEL SECURITY), never an application setting.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "opportunities",
    "opportunity_stage_changes",
    "products",
    "price_books",
    "price_book_entries",
    "quotes",
    "quote_lines",
    "quote_events",
    "quote_number_counters",
    "quote_settings",
    "orders",
    "order_lines",
    "order_status_events",
    "order_number_counters",
    "invoices",
    "invoice_lines",
    "credit_notes",
    "credit_note_lines",
    "payments",
    "billing_number_counters",
)


def upgrade() -> None:
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
    for table in reversed(_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
