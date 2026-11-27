"""Reservation tables (ADR 0040, RP2).

- ``reservation_settings``: one row per VERSION of an organisation's token rule and refund
  policy. Insert-only: a change is a new version, so a reservation can always show the rules it
  was made under.
- ``reservations``: one buyer's hold on one unit for one deal. The database itself refuses a
  second active reservation on the same unit, a status change the rules do not allow, and any
  change to the amount, unit, deal or rules version after the row was made.
- ``reservation_events``: insert-only history of every status change.

The allowed values are written out in the migration too (a migration must not change when the
code does); ``rules.py`` holds the same lists for the service.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import (
    Base,
    TenantOwnedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    VersionedMixin,
)
from app.modules.reservations.rules import AMOUNT_MODES, REFUND_REASONS, STATUSES

_ACTIVE = "status IN ('pending_payment', 'held')"


class ReservationSettings(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    __tablename__ = "reservation_settings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "version_no"),
        ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("version_no >= 1", name="version_positive"),
        CheckConstraint(f"amount_mode IN {AMOUNT_MODES}", name="mode_allowed"),
        CheckConstraint(
            "(amount_mode = 'fixed' AND fixed_amount IS NOT NULL AND percent IS NULL"
            " AND fixed_amount BETWEEN min_amount AND max_amount)"
            " OR (amount_mode = 'percent' AND percent IS NOT NULL AND fixed_amount IS NULL"
            " AND percent > 0 AND percent <= 100)",
            name="mode_fields",
        ),
        CheckConstraint("min_amount > 0 AND min_amount <= max_amount", name="range_valid"),
        CheckConstraint("free_cancel_hours BETWEEN 0 AND 720", name="free_cancel_range"),
        CheckConstraint("kept_percent BETWEEN 0 AND 100", name="kept_percent_range"),
    )

    version_no: Mapped[int] = mapped_column(Integer)
    amount_mode: Mapped[str] = mapped_column(String(10))
    fixed_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    min_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    max_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    free_cancel_hours: Mapped[int] = mapped_column(Integer)
    kept_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Reservation(UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "reservations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "unit_id"],
            ["property_units.tenant_id", "property_units.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "opportunity_id"],
            ["opportunities.tenant_id", "opportunities.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "settings_version"],
            ["reservation_settings.tenant_id", "reservation_settings.version_no"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(f"status IN {STATUSES}", name="status_allowed"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(
            "status <> 'held' OR (paid_at IS NOT NULL AND held_until IS NOT NULL)",
            name="held_is_paid",
        ),
        CheckConstraint(
            "status <> 'refund_due' OR (paid_at IS NOT NULL AND refund_due_amount IS NOT NULL"
            " AND refund_reason IS NOT NULL)",
            name="refund_due_complete",
        ),
        CheckConstraint(
            "status <> 'refunded' OR refund_reference IS NOT NULL", name="refunded_has_reference"
        ),
        CheckConstraint(
            "refund_due_amount IS NULL OR (refund_due_amount >= 0 AND refund_due_amount <= amount)",
            name="refund_within_amount",
        ),
        CheckConstraint(
            f"refund_reason IS NULL OR refund_reason IN {REFUND_REASONS}",
            name="refund_reason_allowed",
        ),
        CheckConstraint(
            "refund_reference IS NULL OR refund_reference ~ '^rfnd_[A-Za-z0-9]{6,30}$'",
            name="refund_reference_format",
        ),
        CheckConstraint("payment_due_at > created_at", name="due_after_creation"),
        # The heart of ADR 0040: one buyer per unit at a time, enforced by the database.
        Index(
            "uq_reservations_one_active_per_unit",
            "tenant_id",
            "unit_id",
            unique=True,
            postgresql_where=text(_ACTIVE),
        ),
        Index("ix_reservations_tenant_id_opportunity_id", "tenant_id", "opportunity_id"),
        Index("ix_reservations_tenant_id_status", "tenant_id", "status"),
    )

    unit_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    settings_version: Mapped[int] = mapped_column(Integer)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(20), server_default=text("'pending_payment'"))
    payment_due_at: Mapped[datetime] = mapped_column()
    paid_at: Mapped[datetime | None] = mapped_column()
    held_until: Mapped[datetime | None] = mapped_column()
    refund_due_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    refund_reason: Mapped[str | None] = mapped_column(String(20))
    refund_reference: Mapped[str | None] = mapped_column(String(40))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)


class ReservationEvent(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    __tablename__ = "reservation_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "reservation_id"],
            ["reservations.tenant_id", "reservations.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(f"to_status IN {STATUSES}", name="to_status_allowed"),
        CheckConstraint(
            f"from_status IS NULL OR from_status IN {STATUSES}", name="from_status_allowed"
        ),
        Index("ix_reservation_events_tenant_id_reservation_id", "tenant_id", "reservation_id"),
    )

    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
    reservation_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(40))
    # None = the system (the worker or the payment webhook), never a guess at a person.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
