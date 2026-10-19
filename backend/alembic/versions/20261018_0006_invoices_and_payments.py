"""Invoices, credit notes, payments, per-tenant billing numbers.

- invoices: from an order; draft -> issued (number, frozen) or discarded. A trigger refuses
  every change to an issued or discarded invoice except its running balance. DELETE revoked.
- invoice_lines, credit_notes, credit_note_lines, payments: insert-only for the application
  (UPDATE / DELETE / TRUNCATE revoked from every role except the schema owner).
- billing_number_counters: last number per tenant and series (invoice, credit_note).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-18
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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


def _fk(table: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", column],
        [f"{target}.tenant_id", f"{target}.id"],
        name=f"fk_{table}_tenant_id_{column}_{target}",
        ondelete="RESTRICT",
    )


def _line_columns() -> list[Any]:
    return [
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("product_code", sa.String(64), nullable=True),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("tax_rate", sa.Numeric(5, 2), nullable=False),
        _money("line_subtotal"),
        _money("line_tax"),
        _money("line_total"),
    ]


def _line_checks(table: str) -> list[Any]:
    return [
        sa.CheckConstraint("position > 0", name=op.f(f"ck_{table}_position_positive")),
        sa.CheckConstraint("quantity > 0", name=op.f(f"ck_{table}_quantity_positive")),
        sa.CheckConstraint("unit_price >= 0", name=op.f(f"ck_{table}_unit_price_not_negative")),
        sa.CheckConstraint(
            "tax_rate >= 0 AND tax_rate <= 100", name=op.f(f"ck_{table}_tax_rate_range")
        ),
        sa.CheckConstraint(
            "line_total = line_subtotal + line_tax",
            name=op.f(f"ck_{table}_line_total_consistent"),
        ),
    ]


def _insert_only(
    table: str, privileges: tuple[str, ...] = ("UPDATE", "DELETE", "TRUNCATE")
) -> None:
    """Revoke rewriting rights from every role except the schema owner (current_user)."""
    listed = ", ".join(f"'{p}'" for p in privileges)
    revoke = ", ".join(privileges)
    op.execute(
        f"""
        DO $$
        DECLARE grantee_name text;
        BEGIN
          FOR grantee_name IN
            SELECT DISTINCT grantee FROM information_schema.role_table_grants
            WHERE table_schema = current_schema() AND table_name = '{table}'
              AND privilege_type IN ({listed})
              AND grantee <> current_user
          LOOP
            EXECUTE format('REVOKE {revoke} ON {table} FROM %I', grantee_name);
          END LOOP;
        END $$;
        """  # noqa: S608 - table and privilege names are constants in this file
    )


def upgrade() -> None:
    op.create_table(
        "billing_number_counters",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("series", sa.String(20), nullable=False),
        sa.Column("last_number", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "series", name="pk_billing_number_counters"),
        _tenant_fk("billing_number_counters"),
        sa.CheckConstraint(
            "series IN ('invoice', 'credit_note')",
            name=op.f("ck_billing_number_counters_series_allowed"),
        ),
    )

    op.create_table(
        "invoices",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=True),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(20), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("customer_reference", sa.String(100), nullable=True),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        _ts("issued_at", nullable=True),
        _ts("discarded_at", nullable=True),
        _money("subtotal"),
        _money("tax_total"),
        _money("total"),
        _money("amount_paid", default=True),
        _money("amount_credited", default=True),
        _money("balance_due"),
        _ts("created_at", default=sa.func.now()),
        _ts("updated_at", default=sa.func.now()),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_invoices"),
        _tenant_fk("invoices"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_invoices_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "number", name="uq_invoices_tenant_id_number"),
        _fk("invoices", "account_id", "accounts"),
        _fk("invoices", "order_id", "orders"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_invoices_tenant_id_created_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'issued', 'discarded')", name=op.f("ck_invoices_status_allowed")
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f("ck_invoices_currency_iso")),
        sa.CheckConstraint(
            "number IS NULL OR number > 0", name=op.f("ck_invoices_number_positive")
        ),
        sa.CheckConstraint(
            "(status = 'issued') = (number IS NOT NULL AND issue_date IS NOT NULL "
            "AND due_date IS NOT NULL AND issued_at IS NOT NULL)",
            name=op.f("ck_invoices_issued_consistent"),
        ),
        sa.CheckConstraint("due_date >= issue_date", name=op.f("ck_invoices_due_after_issue")),
        sa.CheckConstraint(
            "subtotal >= 0 AND tax_total >= 0 AND total = subtotal + tax_total",
            name=op.f("ck_invoices_totals_consistent"),
        ),
        sa.CheckConstraint(
            "amount_paid >= 0 AND amount_credited >= 0 AND balance_due >= 0 "
            "AND balance_due = total - amount_paid - amount_credited",
            name=op.f("ck_invoices_balance_consistent"),
        ),
    )
    op.create_index(
        "uq_invoices_tenant_id_order_id_live",
        "invoices",
        ["tenant_id", "order_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'discarded'"),
    )
    op.create_index("ix_invoices_tenant_id_account_id", "invoices", ["tenant_id", "account_id"])
    op.create_index(
        "ix_invoices_tenant_id_status_due_date", "invoices", ["tenant_id", "status", "due_date"]
    )

    op.create_table(
        "invoice_lines",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        *_line_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_invoice_lines"),
        _tenant_fk("invoice_lines"),
        _fk("invoice_lines", "invoice_id", "invoices"),
        sa.UniqueConstraint(
            "tenant_id",
            "invoice_id",
            "position",
            name="uq_invoice_lines_tenant_id_invoice_id_position",
        ),
        *_line_checks("invoice_lines"),
    )

    op.create_table(
        "credit_notes",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=False),
        _money("subtotal"),
        _money("tax_total"),
        _money("total"),
        _ts("created_at", default=sa.func.clock_timestamp()),
        sa.PrimaryKeyConstraint("id", name="pk_credit_notes"),
        _tenant_fk("credit_notes"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_credit_notes_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "number", name="uq_credit_notes_tenant_id_number"),
        _fk("credit_notes", "invoice_id", "invoices"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_credit_notes_tenant_id_created_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("number > 0", name=op.f("ck_credit_notes_number_positive")),
        sa.CheckConstraint(
            "subtotal >= 0 AND tax_total >= 0 AND total > 0 AND total = subtotal + tax_total",
            name=op.f("ck_credit_notes_totals_consistent"),
        ),
    )
    op.create_index(
        "ix_credit_notes_tenant_id_invoice_id", "credit_notes", ["tenant_id", "invoice_id"]
    )

    op.create_table(
        "credit_note_lines",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("credit_note_id", sa.Uuid(), nullable=False),
        *_line_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_credit_note_lines"),
        _tenant_fk("credit_note_lines"),
        _fk("credit_note_lines", "credit_note_id", "credit_notes"),
        sa.UniqueConstraint(
            "tenant_id",
            "credit_note_id",
            "position",
            name="uq_credit_note_lines_tenant_id_credit_note_id_position",
        ),
        *_line_checks("credit_note_lines"),
    )

    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        _money("amount"),
        sa.Column("received_on", sa.Date(), nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("reference", sa.String(100), nullable=True),
        sa.Column("recorded_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("reverses_payment_id", sa.Uuid(), nullable=True),
        sa.Column("reversal_reason", sa.String(500), nullable=True),
        _ts("created_at", default=sa.func.clock_timestamp()),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_payments"),
        _tenant_fk("payments"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_payments_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id", "reverses_payment_id", name="uq_payments_tenant_id_reverses_payment_id"
        ),
        _fk("payments", "invoice_id", "invoices"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "recorded_by_user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_payments_tenant_id_recorded_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reverses_payment_id"],
            ["payments.tenant_id", "payments.id"],
            name="fk_payments_tenant_id_reverses_payment_id_payments",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_payments_amount_positive")),
        sa.CheckConstraint(
            "method IN ('bank_transfer', 'card', 'cash', 'other')",
            name=op.f("ck_payments_method_allowed"),
        ),
        sa.CheckConstraint(
            "(reverses_payment_id IS NULL) = (reversal_reason IS NULL)",
            name=op.f("ck_payments_reversal_consistent"),
        ),
    )
    op.create_index(
        "ix_payments_tenant_id_invoice_id_seq", "payments", ["tenant_id", "invoice_id", "seq"]
    )

    # Issued invoices are legal documents: once issued (or discarded) nothing may change
    # except the running balance. Enforced in the database, so no code path can bypass it.
    op.execute(
        """
        CREATE FUNCTION invoices_freeze_issued() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.status = 'discarded' THEN
            RAISE EXCEPTION 'invoice % is discarded and cannot be changed', OLD.id
              USING ERRCODE = 'check_violation';
          END IF;
          IF OLD.status = 'issued' AND (
               NEW.status IS DISTINCT FROM OLD.status
            OR NEW.number IS DISTINCT FROM OLD.number
            OR NEW.order_id IS DISTINCT FROM OLD.order_id
            OR NEW.account_id IS DISTINCT FROM OLD.account_id
            OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
            OR NEW.currency IS DISTINCT FROM OLD.currency
            OR NEW.customer_reference IS DISTINCT FROM OLD.customer_reference
            OR NEW.issue_date IS DISTINCT FROM OLD.issue_date
            OR NEW.due_date IS DISTINCT FROM OLD.due_date
            OR NEW.issued_at IS DISTINCT FROM OLD.issued_at
            OR NEW.subtotal IS DISTINCT FROM OLD.subtotal
            OR NEW.tax_total IS DISTINCT FROM OLD.tax_total
            OR NEW.total IS DISTINCT FROM OLD.total
            OR NEW.created_by_user_id IS DISTINCT FROM OLD.created_by_user_id
          ) THEN
            RAISE EXCEPTION 'invoice % is issued and cannot be changed (use a credit note)', OLD.id
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END $$;
        """
    )
    op.execute(
        "CREATE TRIGGER trg_invoices_freeze_issued BEFORE UPDATE ON invoices "
        "FOR EACH ROW EXECUTE FUNCTION invoices_freeze_issued()"
    )
    _insert_only("invoices", ("DELETE", "TRUNCATE"))
    for table in ("invoice_lines", "credit_notes", "credit_note_lines", "payments"):
        _insert_only(table)


def downgrade() -> None:
    op.drop_table("payments")
    op.drop_table("credit_note_lines")
    op.drop_table("credit_notes")
    op.drop_table("invoice_lines")
    op.execute("DROP TRIGGER IF EXISTS trg_invoices_freeze_issued ON invoices")
    op.drop_table("invoices")
    op.execute("DROP FUNCTION IF EXISTS invoices_freeze_issued()")
    op.drop_table("billing_number_counters")
