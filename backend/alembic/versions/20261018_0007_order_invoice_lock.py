"""Order invoice lock: orders.invoiced_at.

- orders.invoiced_at: set while the order has a live (draft or issued) invoice, cleared when
  the draft is discarded. The invoices module sets it through orders.api, so the orders module
  can refuse cancellation without importing invoices.
- CHECK: a cancelled order never carries the lock.
- Backfill: orders that already have a live invoice get the lock (cancelled orders are left
  alone: they were cancelled before this rule existed).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("invoiced_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "UPDATE orders o SET invoiced_at = i.created_at FROM invoices i "
        "WHERE i.tenant_id = o.tenant_id AND i.order_id = o.id "
        "AND i.status <> 'discarded' AND o.status <> 'cancelled'"
    )
    op.create_check_constraint(
        op.f("ck_orders_not_cancelled_while_invoiced"),
        "orders",
        "NOT (status = 'cancelled' AND invoiced_at IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_orders_not_cancelled_while_invoiced"), "orders", type_="check")
    op.drop_column("orders", "invoiced_at")
