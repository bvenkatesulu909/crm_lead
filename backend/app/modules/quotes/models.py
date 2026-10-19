"""Quotes, their lines and their status history.

Status flow (rules in rules.py):
    draft ──submit──► pending_approval ──approve──► approved ──send──► sent ──► accepted
      ▲                    │ reject (back to draft)    (if no approval is needed,  └─► declined
      └────────────────────┘                            submit goes straight to approved)
    Any quote that is not accepted can be REVISED: a new draft copy is made and the old quote
    becomes "superseded". An accepted quote can be turned into an order (once).

All money is calculated by the server from the price book: list price × quantity, minus the
line discount, plus tax - rounded per line so the printed lines add up to the printed total.
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

QUOTE_STATUSES = (
    "draft", "pending_approval", "approved", "sent", "accepted", "declined", "superseded",
)  # fmt: skip


def _fk(column: str, table: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["tenant_id", column], [f"{table}.tenant_id", f"{table}.id"], ondelete="RESTRICT"
    )


def _money() -> Mapped[Decimal]:
    return mapped_column(Numeric(18, 2), server_default=text("0"))


class Quote(UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "quotes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "number", "revision"),
        _fk("account_id", "accounts"),
        _fk("opportunity_id", "opportunities"),
        _fk("contact_id", "contacts"),
        _fk("owner_id", "users"),
        _fk("created_by_user_id", "users"),
        _fk("approved_by_user_id", "users"),
        _fk("price_book_id", "price_books"),
        _fk("revision_of_id", "quotes"),
        _fk("order_id", "orders"),
        CheckConstraint(f"status IN {QUOTE_STATUSES}", name="status_allowed"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso"),
        CheckConstraint("revision >= 1", name="revision_positive"),
        CheckConstraint("order_id IS NULL OR status = 'accepted'", name="order_only_when_accepted"),
        Index("ix_quotes_tenant_id_account_id", "tenant_id", "account_id"),
        Index("ix_quotes_tenant_id_opportunity_id", "tenant_id", "opportunity_id"),
        Index("ix_quotes_tenant_id_status", "tenant_id", "status"),
    )

    number: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    revision_of_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(200))
    account_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    price_book_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20), server_default=text("'draft'"))
    valid_until: Mapped[date] = mapped_column(Date)
    customer_note: Mapped[str | None] = mapped_column(Text)  # printed on the quote
    internal_note: Mapped[str | None] = mapped_column(Text)  # staff only
    gross_total: Mapped[Decimal] = _money()  # before discounts and tax
    discount_total: Mapped[Decimal] = _money()
    subtotal: Mapped[Decimal] = _money()  # after discounts, before tax
    tax_total: Mapped[Decimal] = _money()
    total: Mapped[Decimal] = _money()
    max_discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default=text("0"))
    needs_approval: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    submitted_at: Mapped[datetime | None] = mapped_column(default=None)
    approved_at: Mapped[datetime | None] = mapped_column(default=None)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    sent_at: Mapped[datetime | None] = mapped_column(default=None)
    decided_at: Mapped[datetime | None] = mapped_column(default=None)  # accepted or declined
    decision_note: Mapped[str | None] = mapped_column(String(500))
    order_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class QuoteLine(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    __tablename__ = "quote_lines"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "quote_id"], ["quotes.tenant_id", "quotes.id"], ondelete="CASCADE"
        ),
        _fk("product_id", "products"),
        UniqueConstraint("tenant_id", "quote_id", "position"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("discount_percent >= 0 AND discount_percent <= 100", name="discount_range"),
    )

    quote_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    position: Mapped[int] = mapped_column(Integer)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    sku: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(500))
    unit: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    list_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))  # from the price book
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    net_unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    line_gross: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    line_discount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    line_subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    line_tax: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    line_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))


class QuoteEvent(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    """Insert-only history: every status change, who made it and why."""

    __tablename__ = "quote_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "quote_id"], ["quotes.tenant_id", "quotes.id"], ondelete="RESTRICT"
        ),
        _fk("actor_user_id", "users"),
        Index("ix_quote_events_tenant_id_quote_id", "tenant_id", "quote_id"),
    )

    quote_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(server_default=func.clock_timestamp())
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))


class QuoteNumberCounter(Base):
    __tablename__ = "quote_number_counters"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="RESTRICT"), primary_key=True
    )
    last_number: Mapped[int] = mapped_column(Integer)


class QuoteSettings(VersionedMixin, Base):
    """Per-organisation quote settings. No row = the defaults in rules.py."""

    __tablename__ = "quote_settings"
    __table_args__ = (
        CheckConstraint(
            "approval_limit_percent >= 0 AND approval_limit_percent <= 100",
            name="approval_limit_range",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "updated_by_user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="RESTRICT"), primary_key=True
    )
    approval_limit_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
