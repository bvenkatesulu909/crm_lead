"""Contracts, their history and their numbering.

Status flow (rules come with step C2, see docs/contracts.md):
    draft ──activate──► active ──terminate──► terminated
                          ├─ end date passes (no auto-renew) ──► expired
                          └─ renewed (a new draft linked back, then activated) ──► renewed

The database refuses impossible rows on its own (dates in the wrong order, a terminated contract
without a reason, an active contract without dates), so a bug in the application cannot store
them. Money is NUMERIC, never a float.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
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

CONTRACT_STATUSES = ("draft", "active", "expired", "terminated", "renewed")
BILLING_FREQUENCIES = ("one_time", "monthly", "quarterly", "annually")


def _fk(column: str, table: str) -> ForeignKeyConstraint:
    """A tenant-scoped reference: the other row must belong to the same organisation."""
    return ForeignKeyConstraint(
        ["tenant_id", column], [f"{table}.tenant_id", f"{table}.id"], ondelete="RESTRICT"
    )


class Contract(UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "contracts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "number"),
        _fk("account_id", "accounts"),
        _fk("contact_id", "contacts"),
        _fk("owner_id", "users"),
        _fk("created_by_user_id", "users"),
        _fk("quote_id", "quotes"),
        _fk("opportunity_id", "opportunities"),
        _fk("renewed_from_id", "contracts"),
        CheckConstraint(f"status IN {CONTRACT_STATUSES}", name="status_allowed"),
        CheckConstraint(f"billing_frequency IN {BILLING_FREQUENCIES}", name="billing_allowed"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso"),
        CheckConstraint("total_value >= 0", name="value_not_negative"),
        CheckConstraint(
            "start_date IS NULL OR end_date IS NULL OR end_date >= start_date",
            name="dates_in_order",
        ),
        CheckConstraint(
            "status = 'draft' OR (start_date IS NOT NULL AND end_date IS NOT NULL)",
            name="dates_when_not_draft",
        ),
        CheckConstraint(
            "renewal_notice_days >= 0 AND renewal_notice_days <= 365", name="notice_days_range"
        ),
        CheckConstraint(
            "renewal_term_months IS NULL "
            "OR (renewal_term_months >= 1 AND renewal_term_months <= 120)",
            name="renewal_term_range",
        ),
        CheckConstraint(
            "(status = 'terminated') = (terminated_at IS NOT NULL)", name="terminated_has_date"
        ),
        CheckConstraint(
            "status = 'terminated' OR termination_reason IS NULL", name="reason_only_if_terminated"
        ),
        CheckConstraint(
            "status <> 'terminated' OR termination_reason IS NOT NULL",
            name="terminated_has_reason",
        ),
        Index("ix_contracts_tenant_id_account_id", "tenant_id", "account_id"),
        Index("ix_contracts_tenant_id_owner_id", "tenant_id", "owner_id"),
        Index("ix_contracts_tenant_id_status", "tenant_id", "status"),
        # The daily worker looks for contracts that are about to end or have ended.
        Index("ix_contracts_tenant_id_end_date", "tenant_id", "end_date"),
    )

    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), server_default=text("'draft'"))
    account_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    quote_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    # A renewal is a new contract that points back at the one it replaces.
    renewed_from_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    auto_renew: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    renewal_notice_days: Mapped[int] = mapped_column(Integer, server_default=text("30"))
    renewal_term_months: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), server_default=text("'EUR'"))
    total_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    billing_frequency: Mapped[str] = mapped_column(String(20), server_default=text("'annually'"))
    terms: Mapped[str | None] = mapped_column(Text)
    terminated_at: Mapped[datetime | None] = mapped_column()
    termination_reason: Mapped[str | None] = mapped_column(String(500))
    # Set by the worker when the "renewal is coming" reminder went out, so it goes out only once.
    renewal_reminded_at: Mapped[datetime | None] = mapped_column()


class ContractEvent(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    """Insert-only history: every status change and note, who made it and when."""

    __tablename__ = "contract_events"
    __table_args__ = (
        _fk("contract_id", "contracts"),
        _fk("actor_user_id", "users"),
        CheckConstraint(
            "event_type IN ('created', 'status_changed', 'note', 'renewal_reminder', 'expired')",
            name="event_type_allowed",
        ),
        Index("ix_contract_events_tenant_id_contract_id", "tenant_id", "contract_id"),
    )

    contract_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    event_type: Mapped[str] = mapped_column(String(30))
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str | None] = mapped_column(String(20))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(server_default=func.clock_timestamp())
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))


class ContractNumberCounter(Base):
    __tablename__ = "contract_number_counters"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="RESTRICT"), primary_key=True
    )
    last_number: Mapped[int] = mapped_column(Integer)
