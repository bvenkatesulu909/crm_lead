"""Reservations: token-amount holds on units (ADR 0040, RP2).

Revision ID: 0087
Revises: 0086
Create Date: 2026-11-27

Three tables, each with ENABLE + FORCE row-level security and the tenant policy (ADR 0009):

- ``reservation_settings`` - versions of an organisation's token rule and refund policy;
  insert-only (a trigger refuses UPDATE and DELETE, the application role loses them too);
- ``reservations`` - the database refuses a second ACTIVE reservation on the same unit
  (partial unique index), any status change outside the allowed list, any change to the amount,
  unit, deal, rules version, creator or payment deadline, and every DELETE;
- ``reservation_events`` - insert-only history of status changes.

The allowed statuses, changes and reasons are written out here on purpose: a migration must not
change when the code does.
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0087"
down_revision: str | None = "0086"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = (
    "('pending_payment', 'held', 'expired', 'cancelled', 'converted', 'refund_due', 'refunded')"
)
REASONS = (
    "('late_payment', 'unit_taken', 'seller_cancelled', 'unit_withdrawn', 'buyer_cancelled',"
    " 'hold_lapsed')"
)
# (from, to) pairs a reservation may move along; everything else is refused by the trigger.
TRANSITIONS = (
    "('pending_payment','held'), ('pending_payment','expired'), ('pending_payment','cancelled'),"
    " ('pending_payment','refund_due'), ('held','converted'), ('held','refund_due'),"
    " ('expired','refund_due'), ('cancelled','refund_due'), ('refund_due','refunded')"
)


def _tenant_policy(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY {table}_tenant_isolation ON {table}
            USING (tenant_id = crm_current_tenant())
            WITH CHECK (tenant_id = crm_current_tenant());
        """
    )


def _revoke(table: str, privileges: str) -> None:
    """Take privileges from every role but the owner (the application role among them).

    ``table`` and ``privileges`` are constants of this file, never input.
    """
    op.execute(
        f"""
        DO $$
        DECLARE grantee_name text;
        BEGIN
          FOR grantee_name IN
            SELECT DISTINCT grantee FROM information_schema.role_table_grants
            WHERE table_schema = current_schema() AND table_name = '{table}'
              AND grantee <> current_user
          LOOP
            EXECUTE format('REVOKE {privileges} ON {table} FROM %I', grantee_name);
          END LOOP;
        END $$;
        """  # noqa: S608 - table and privilege names are constants in this file
    )


def _insert_only(table: str) -> None:
    op.execute(
        f"""
        CREATE FUNCTION {table}_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION '{table} rows cannot be changed or deleted';
        END
        $$;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {table}_guard BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION {table}_guard();
        """
    )
    _revoke(table, "UPDATE, DELETE, TRUNCATE")


def _tenant_fk(table: str) -> Any:
    return sa.ForeignKeyConstraint(
        ["tenant_id"],
        ["tenants.id"],
        name=op.f(f"fk_{table}_tenant_id_tenants"),
        ondelete="RESTRICT",
    )


def _creator_fk(table: str) -> Any:
    return sa.ForeignKeyConstraint(
        ["tenant_id", "created_by_user_id"],
        ["users.tenant_id", "users.id"],
        name=op.f(f"fk_{table}_tenant_id_created_by_user_id_users"),
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    op.create_table(
        "reservation_settings",
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("amount_mode", sa.String(length=10), nullable=False),
        sa.Column("fixed_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("percent", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("min_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("max_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("free_cancel_hours", sa.Integer(), nullable=False),
        sa.Column("kept_percent", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "version_no >= 1", name=op.f("ck_reservation_settings_version_positive")
        ),
        sa.CheckConstraint(
            "amount_mode IN ('fixed', 'percent')", name=op.f("ck_reservation_settings_mode_allowed")
        ),
        sa.CheckConstraint(
            "(amount_mode = 'fixed' AND fixed_amount IS NOT NULL AND percent IS NULL"
            " AND fixed_amount BETWEEN min_amount AND max_amount)"
            " OR (amount_mode = 'percent' AND percent IS NOT NULL AND fixed_amount IS NULL"
            " AND percent > 0 AND percent <= 100)",
            name=op.f("ck_reservation_settings_mode_fields"),
        ),
        sa.CheckConstraint(
            "min_amount > 0 AND min_amount <= max_amount",
            name=op.f("ck_reservation_settings_range_valid"),
        ),
        sa.CheckConstraint(
            "free_cancel_hours BETWEEN 0 AND 720",
            name=op.f("ck_reservation_settings_free_cancel_range"),
        ),
        sa.CheckConstraint(
            "kept_percent BETWEEN 0 AND 100",
            name=op.f("ck_reservation_settings_kept_percent_range"),
        ),
        _creator_fk("reservation_settings"),
        _tenant_fk("reservation_settings"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reservation_settings")),
        sa.UniqueConstraint(
            "tenant_id", "version_no", name=op.f("uq_reservation_settings_tenant_id_version_no")
        ),
    )
    _tenant_policy("reservation_settings")
    _insert_only("reservation_settings")

    op.create_table(
        "reservations",
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("settings_version", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'pending_payment'"),
            nullable=False,
        ),
        sa.Column("payment_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("held_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refund_due_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("refund_reason", sa.String(length=20), nullable=True),
        sa.Column("refund_reference", sa.String(length=40), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(f"status IN {STATUSES}", name=op.f("ck_reservations_status_allowed")),
        sa.CheckConstraint("amount > 0", name=op.f("ck_reservations_amount_positive")),
        sa.CheckConstraint(
            "status <> 'held' OR (paid_at IS NOT NULL AND held_until IS NOT NULL)",
            name=op.f("ck_reservations_held_is_paid"),
        ),
        sa.CheckConstraint(
            "status <> 'refund_due' OR (paid_at IS NOT NULL AND refund_due_amount IS NOT NULL"
            " AND refund_reason IS NOT NULL)",
            name=op.f("ck_reservations_refund_due_complete"),
        ),
        sa.CheckConstraint(
            "status <> 'refunded' OR refund_reference IS NOT NULL",
            name=op.f("ck_reservations_refunded_has_reference"),
        ),
        sa.CheckConstraint(
            "refund_due_amount IS NULL OR (refund_due_amount >= 0 AND refund_due_amount <= amount)",
            name=op.f("ck_reservations_refund_within_amount"),
        ),
        sa.CheckConstraint(
            f"refund_reason IS NULL OR refund_reason IN {REASONS}",
            name=op.f("ck_reservations_refund_reason_allowed"),
        ),
        sa.CheckConstraint(
            "refund_reference IS NULL OR refund_reference ~ '^rfnd_[A-Za-z0-9]{6,30}$'",
            name=op.f("ck_reservations_refund_reference_format"),
        ),
        sa.CheckConstraint(
            "payment_due_at > created_at", name=op.f("ck_reservations_due_after_creation")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "unit_id"],
            ["property_units.tenant_id", "property_units.id"],
            name=op.f("fk_reservations_tenant_id_unit_id_property_units"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "opportunity_id"],
            ["opportunities.tenant_id", "opportunities.id"],
            name=op.f("fk_reservations_tenant_id_opportunity_id_opportunities"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "settings_version"],
            ["reservation_settings.tenant_id", "reservation_settings.version_no"],
            name=op.f("fk_reservations_tenant_id_settings_version_reservation_settings"),
            ondelete="RESTRICT",
        ),
        _creator_fk("reservations"),
        _tenant_fk("reservations"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reservations")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_reservations_tenant_id_id")),
    )
    op.create_index(
        "uq_reservations_one_active_per_unit",
        "reservations",
        ["tenant_id", "unit_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending_payment', 'held')"),
    )
    op.create_index(
        "ix_reservations_tenant_id_opportunity_id", "reservations", ["tenant_id", "opportunity_id"]
    )
    op.create_index("ix_reservations_tenant_id_status", "reservations", ["tenant_id", "status"])
    _tenant_policy("reservations")
    op.execute(
        f"""
        CREATE FUNCTION reservations_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'reservations cannot be deleted';
          END IF;
          IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
             OR NEW.unit_id IS DISTINCT FROM OLD.unit_id
             OR NEW.opportunity_id IS DISTINCT FROM OLD.opportunity_id
             OR NEW.settings_version IS DISTINCT FROM OLD.settings_version
             OR NEW.amount IS DISTINCT FROM OLD.amount
             OR NEW.created_by_user_id IS DISTINCT FROM OLD.created_by_user_id
             OR NEW.created_at IS DISTINCT FROM OLD.created_at
             OR NEW.payment_due_at IS DISTINCT FROM OLD.payment_due_at THEN
            RAISE EXCEPTION 'reservation terms cannot be changed';
          END IF;
          IF NEW.status IS DISTINCT FROM OLD.status
             AND (OLD.status, NEW.status) NOT IN ({TRANSITIONS}) THEN
            RAISE EXCEPTION 'reservation cannot go from % to %', OLD.status, NEW.status;
          END IF;
          RETURN NEW;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER reservations_guard BEFORE UPDATE OR DELETE ON reservations
            FOR EACH ROW EXECUTE FUNCTION reservations_guard();
        """
    )
    _revoke("reservations", "DELETE, TRUNCATE")

    op.create_table(
        "reservation_events",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("reservation_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=True),
        sa.Column("to_status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            f"to_status IN {STATUSES}", name=op.f("ck_reservation_events_to_status_allowed")
        ),
        sa.CheckConstraint(
            f"from_status IS NULL OR from_status IN {STATUSES}",
            name=op.f("ck_reservation_events_from_status_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reservation_id"],
            ["reservations.tenant_id", "reservations.id"],
            name=op.f("fk_reservation_events_tenant_id_reservation_id_reservations"),
            ondelete="RESTRICT",
        ),
        _tenant_fk("reservation_events"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reservation_events")),
    )
    op.create_index(
        "ix_reservation_events_tenant_id_reservation_id",
        "reservation_events",
        ["tenant_id", "reservation_id"],
    )
    _tenant_policy("reservation_events")
    _insert_only("reservation_events")


def downgrade() -> None:
    op.drop_table("reservation_events")
    op.execute("DROP FUNCTION IF EXISTS reservation_events_guard();")
    op.drop_table("reservations")
    op.execute("DROP FUNCTION IF EXISTS reservations_guard();")
    op.drop_table("reservation_settings")
    op.execute("DROP FUNCTION IF EXISTS reservation_settings_guard();")
