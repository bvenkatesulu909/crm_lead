"""Orders: orders, order lines, status history, per-tenant order numbers.

- orders: belongs to a customer account (same tenant, composite FK); status lifecycle,
  currency, customer reference, staff-only note, tracking, server-calculated totals.
- order_lines: snapshot of what was ordered (quantity, price, tax rate and amounts).
- order_status_events: status history. Append-only for the application
  (UPDATE / DELETE / TRUNCATE revoked from every role except the schema owner).
- order_number_counters: last order number per tenant (SO-0001, SO-0002, ...).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-18
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = "('draft', 'confirmed', 'in_fulfilment', 'shipped', 'delivered', 'cancelled')"


def _ts(name: str, *, nullable: bool = False, default: Any = None) -> sa.Column[Any]:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=default, nullable=nullable)


def _money(name: str, *, default: bool = False) -> sa.Column[Any]:
    return sa.Column(
        name, sa.Numeric(18, 2), server_default=sa.text("0") if default else None, nullable=False
    )


def _tenant_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"], ["tenants.id"], name=f"fk_{table}_tenant_id_tenants", ondelete="RESTRICT"
    )


def _order_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", "order_id"],
        ["orders.tenant_id", "orders.id"],
        name=f"fk_{table}_tenant_id_order_id_orders",
        ondelete="RESTRICT",
    )


def _user_fk(table: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", column],
        ["users.tenant_id", "users.id"],
        name=f"fk_{table}_tenant_id_{column}_users",
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    op.create_table(
        "order_number_counters",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("last_number", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", name="pk_order_number_counters"),
        _tenant_fk("order_number_counters"),
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(20), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("customer_reference", sa.String(100), nullable=True),
        sa.Column("internal_note", sa.Text(), nullable=True),
        sa.Column("expected_delivery_date", sa.Date(), nullable=True),
        sa.Column("tracking_reference", sa.String(200), nullable=True),
        _money("subtotal", default=True),
        _money("tax_total", default=True),
        _money("total", default=True),
        _ts("confirmed_at", nullable=True),
        _ts("shipped_at", nullable=True),
        _ts("delivered_at", nullable=True),
        _ts("cancelled_at", nullable=True),
        sa.Column("cancellation_reason", sa.String(500), nullable=True),
        _ts("created_at", default=sa.func.now()),
        _ts("updated_at", default=sa.func.now()),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_orders"),
        _tenant_fk("orders"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_orders_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "number", name="uq_orders_tenant_id_number"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            ["accounts.tenant_id", "accounts.id"],
            name="fk_orders_tenant_id_account_id_accounts",
            ondelete="RESTRICT",
        ),
        _user_fk("orders", "created_by_user_id"),
        sa.CheckConstraint(f"status IN {STATUSES}", name=op.f("ck_orders_status_allowed")),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f("ck_orders_currency_iso")),
        sa.CheckConstraint("number > 0", name=op.f("ck_orders_number_positive")),
        sa.CheckConstraint(
            "subtotal >= 0 AND tax_total >= 0 AND total = subtotal + tax_total",
            name=op.f("ck_orders_totals_consistent"),
        ),
        sa.CheckConstraint(
            "(status = 'cancelled') = "
            "(cancelled_at IS NOT NULL AND cancellation_reason IS NOT NULL)",
            name=op.f("ck_orders_cancelled_consistent"),
        ),
        sa.CheckConstraint(
            "CASE status WHEN 'draft' THEN confirmed_at IS NULL "
            "WHEN 'cancelled' THEN true ELSE confirmed_at IS NOT NULL END",
            name=op.f("ck_orders_confirmed_consistent"),
        ),
    )
    op.create_index("ix_orders_tenant_id_status", "orders", ["tenant_id", "status"])
    op.create_index("ix_orders_tenant_id_account_id", "orders", ["tenant_id", "account_id"])
    op.create_index("ix_orders_tenant_id_created_at", "orders", ["tenant_id", "created_at"])

    op.create_table(
        "order_lines",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("product_code", sa.String(64), nullable=True),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("tax_rate", sa.Numeric(5, 2), nullable=False),
        _money("line_subtotal"),
        _money("line_tax"),
        _money("line_total"),
        sa.PrimaryKeyConstraint("id", name="pk_order_lines"),
        _tenant_fk("order_lines"),
        _order_fk("order_lines"),
        sa.UniqueConstraint(
            "tenant_id", "order_id", "position", name="uq_order_lines_tenant_id_order_id_position"
        ),
        sa.CheckConstraint("position > 0", name=op.f("ck_order_lines_position_positive")),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_order_lines_quantity_positive")),
        sa.CheckConstraint("unit_price >= 0", name=op.f("ck_order_lines_unit_price_not_negative")),
        sa.CheckConstraint(
            "tax_rate >= 0 AND tax_rate <= 100", name=op.f("ck_order_lines_tax_rate_range")
        ),
        sa.CheckConstraint(
            "line_total = line_subtotal + line_tax",
            name=op.f("ck_order_lines_line_total_consistent"),
        ),
    )

    op.create_table(
        "order_status_events",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=True),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        _ts("created_at", default=sa.func.clock_timestamp()),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_order_status_events"),
        _tenant_fk("order_status_events"),
        _order_fk("order_status_events"),
        _user_fk("order_status_events", "actor_user_id"),
        sa.CheckConstraint(
            f"to_status IN {STATUSES}", name=op.f("ck_order_status_events_to_status_allowed")
        ),
    )
    op.create_index(
        "ix_order_status_events_tenant_id_order_id_seq",
        "order_status_events",
        ["tenant_id", "order_id", "seq"],
    )
    # The status history is a record of what happened: the application may add, never rewrite.
    op.execute(
        """
        DO $$
        DECLARE grantee_name text;
        BEGIN
          FOR grantee_name IN
            SELECT DISTINCT grantee FROM information_schema.role_table_grants
            WHERE table_schema = current_schema() AND table_name = 'order_status_events'
              AND privilege_type IN ('UPDATE', 'DELETE', 'TRUNCATE')
              AND grantee <> current_user
          LOOP
            EXECUTE format(
              'REVOKE UPDATE, DELETE, TRUNCATE ON order_status_events FROM %I', grantee_name
            );
          END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_table("order_status_events")
    op.drop_table("order_lines")
    op.drop_table("orders")
    op.drop_table("order_number_counters")
