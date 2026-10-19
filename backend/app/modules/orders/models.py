"""Order tables: ``orders``, ``order_lines``, ``order_status_events``, ``order_number_counters``.

Money columns are NUMERIC (exact decimals). Totals are always calculated by the server
(see rules.py) and stored, so a confirmed order keeps exactly the amounts it was confirmed with.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
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

ORDER_STATUSES = ("draft", "confirmed", "in_fulfilment", "shipped", "delivered", "cancelled")


class Order(UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, VersionedMixin, Base):
    """A customer order for one account. Editable only while it is a draft."""

    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        # Human-friendly number, unique within the tenant (SO-0001, SO-0002, ...).
        UniqueConstraint("tenant_id", "number"),
        ForeignKeyConstraint(
            ["tenant_id", "account_id"], ["accounts.tenant_id", "accounts.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(f"status IN {ORDER_STATUSES}", name="status_allowed"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso"),
        CheckConstraint("number > 0", name="number_positive"),
        CheckConstraint(
            "subtotal >= 0 AND tax_total >= 0 AND total = subtotal + tax_total",
            name="totals_consistent",
        ),
        CheckConstraint(
            "(status = 'cancelled') = "
            "(cancelled_at IS NOT NULL AND cancellation_reason IS NOT NULL)",
            name="cancelled_consistent",
        ),
        # Drafts were never confirmed; every later status except "cancelled" (a cancelled
        # draft) must have been.
        CheckConstraint(
            "CASE status WHEN 'draft' THEN confirmed_at IS NULL "
            "WHEN 'cancelled' THEN true ELSE confirmed_at IS NOT NULL END",
            name="confirmed_consistent",
        ),
        # A cancelled order can never carry a live invoice (see ``invoiced_at``).
        CheckConstraint(
            "NOT (status = 'cancelled' AND invoiced_at IS NOT NULL)",
            name="not_cancelled_while_invoiced",
        ),
        Index("ix_orders_tenant_id_status", "tenant_id", "status"),
        Index("ix_orders_tenant_id_account_id", "tenant_id", "account_id"),
        Index("ix_orders_tenant_id_created_at", "tenant_id", "created_at"),
    )

    number: Mapped[int] = mapped_column(Integer)
    account_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(20), server_default=text("'draft'"))
    currency: Mapped[str] = mapped_column(String(3))
    # The customer's own purchase-order number, shown to them in the portal.
    customer_reference: Mapped[str | None] = mapped_column(String(100))
    # Staff-only note: never returned by the portal API.
    internal_note: Mapped[str | None] = mapped_column(Text)
    expected_delivery_date: Mapped[date | None] = mapped_column(Date)
    tracking_reference: Mapped[str | None] = mapped_column(String(200))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    tax_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    confirmed_at: Mapped[datetime | None] = mapped_column(default=None)
    shipped_at: Mapped[datetime | None] = mapped_column(default=None)
    delivered_at: Mapped[datetime | None] = mapped_column(default=None)
    cancelled_at: Mapped[datetime | None] = mapped_column(default=None)
    # Shown to the customer: staff are told so when they cancel.
    cancellation_reason: Mapped[str | None] = mapped_column(String(500))
    # Set while the order has a live (draft or issued) invoice; cleared when the draft is
    # discarded. The invoices module sets it through ``orders.api`` so orders never has to
    # import invoices. While it is set the order cannot be cancelled.
    invoiced_at: Mapped[datetime | None] = mapped_column(default=None)


class OrderLine(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    """One position of an order. Line amounts are a SNAPSHOT: later price changes (e.g. in a
    future product catalogue) never change an existing order."""

    __tablename__ = "order_lines"
    __table_args__ = (
        UniqueConstraint("tenant_id", "order_id", "position"),
        ForeignKeyConstraint(
            ["tenant_id", "order_id"], ["orders.tenant_id", "orders.id"], ondelete="RESTRICT"
        ),
        CheckConstraint("position > 0", name="position_positive"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_not_negative"),
        CheckConstraint("tax_rate >= 0 AND tax_rate <= 100", name="tax_rate_range"),
        CheckConstraint("line_total = line_subtotal + line_tax", name="line_total_consistent"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    position: Mapped[int] = mapped_column(Integer)
    product_code: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))  # percent, e.g. 19.00
    line_subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    line_tax: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    line_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))


class OrderStatusEvent(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    """Status history. Append-only for the application (see migration 0005).
    ``note`` is staff-only; customers see just the status and the time."""

    __tablename__ = "order_status_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "order_id"], ["orders.tenant_id", "orders.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "actor_user_id"], ["users.tenant_id", "users.id"], ondelete="RESTRICT"
        ),
        CheckConstraint(f"to_status IN {ORDER_STATUSES}", name="to_status_allowed"),
        Index("ix_order_status_events_tenant_id_order_id_seq", "tenant_id", "order_id", "seq"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(server_default=func.clock_timestamp())
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))


class OrderNumberCounter(Base):
    """Last order number used per tenant (incremented atomically, see repository)."""

    __tablename__ = "order_number_counters"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="RESTRICT"), primary_key=True
    )
    last_number: Mapped[int] = mapped_column(Integer)
