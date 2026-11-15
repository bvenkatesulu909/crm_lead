"""UPI as a payment method and one payment per gateway payment id (ADR 0031, UP2).

Revision ID: 0062
Revises: 0061
Create Date: 2026-11-13

``payments.method`` may now be ``upi``. A UPI payment is identified by the gateway's payment id,
kept in ``reference``: a unique partial index refuses a second payment (not a reversal) with the
same reference in an organisation, so a repeated webhook event cannot add money twice. The method
list is written out here on purpose: a migration must not change when the code does.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0062"
down_revision: str | None = "0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_payments_method_allowed"), "payments", type_="check")
    op.create_check_constraint(
        op.f("ck_payments_method_allowed"),
        "payments",
        "method IN ('bank_transfer', 'card', 'cash', 'other', 'upi')",
    )
    # Two links made in one transaction must still sort in the order they were made.
    op.execute("ALTER TABLE payment_links ALTER COLUMN created_at SET DEFAULT clock_timestamp();")
    op.create_index(
        "uq_payments_upi_reference",
        "payments",
        ["tenant_id", "reference"],
        unique=True,
        postgresql_where="method = 'upi' AND reverses_payment_id IS NULL",
    )


def downgrade() -> None:
    op.execute("ALTER TABLE payment_links ALTER COLUMN created_at SET DEFAULT now();")
    op.drop_index("uq_payments_upi_reference", table_name="payments")
    op.drop_constraint(op.f("ck_payments_method_allowed"), "payments", type_="check")
    op.create_check_constraint(
        op.f("ck_payments_method_allowed"),
        "payments",
        "method IN ('bank_transfer', 'card', 'cash', 'other')",
    )
