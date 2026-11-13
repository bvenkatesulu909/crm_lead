"""Payment links and the webhook events about them (ADR 0031, migration 0061).

``payment_links``: one Razorpay link for the balance of one invoice. At most one is ``created``
(open) per invoice - the database refuses a second. The row can change status but never be deleted.

``payment_events``: one row per VERIFIED webhook delivery, stored before anything acts on it. Only
the facts the worker needs are kept (``facts``): no customer e-mail or phone, no card or UPI data.
Rows cannot be changed except to set ``outcome`` and ``processed_at`` once, and cannot be deleted
before 365 days: a trigger and a column-level grant (two locks).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantOwnedMixin, UUIDPrimaryKeyMixin
from app.modules.payment_links import rules

_MAX_PAISE = rules.MAX_PAISE


class PaymentLink(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    __tablename__ = "payment_links"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("provider_link_id"),
        UniqueConstraint("tenant_id", "reference_id"),
        ForeignKeyConstraint(
            ["tenant_id", "invoice_id"], ["invoices.tenant_id", "invoices.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(f"status IN {rules.LINK_STATUSES}", name="status_allowed"),
        CheckConstraint("currency = 'INR'", name="currency_inr"),
        CheckConstraint(
            f"amount_paise BETWEEN {rules.MIN_PAISE} AND {_MAX_PAISE}", name="amount_range"
        ),
        CheckConstraint(
            "(status = 'paid') = (provider_payment_id IS NOT NULL)", name="paid_has_payment"
        ),
        CheckConstraint("(status = 'paid') = (paid_at IS NOT NULL)", name="paid_has_time"),
        Index("ix_payment_links_tenant_id_invoice_id", "tenant_id", "invoice_id"),
        # One open link per invoice. A new one is created only after the old one is cancelled.
        Index(
            "uq_payment_links_one_open_per_invoice",
            "tenant_id",
            "invoice_id",
            unique=True,
            postgresql_where=text("status = 'created'"),
        ),
    )

    invoice_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    provider_link_id: Mapped[str] = mapped_column(String(60))
    reference_id: Mapped[str] = mapped_column(String(rules.REFERENCE_MAX_LENGTH))
    short_url: Mapped[str] = mapped_column(Text)
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), server_default=text("'INR'"))
    status: Mapped[str] = mapped_column(String(10), server_default=text("'created'"))
    expires_at: Mapped[datetime] = mapped_column()
    provider_payment_id: Mapped[str | None] = mapped_column(String(60))
    paid_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class PaymentEvent(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    __tablename__ = "payment_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider_event_id"),
        ForeignKeyConstraint(
            ["tenant_id", "payment_link_id"],
            ["payment_links.tenant_id", "payment_links.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "outcome IS NULL OR outcome IN "
            "('applied', 'already_applied', 'amount_mismatch', 'currency_mismatch', "
            "'invoice_closed', 'ignored')",
            name="outcome_allowed",
        ),
        CheckConstraint("(outcome IS NULL) = (processed_at IS NULL)", name="processed_consistent"),
        CheckConstraint("jsonb_typeof(facts) = 'object'", name="facts_is_object"),
        Index("ix_payment_events_tenant_id_payment_link_id", "tenant_id", "payment_link_id"),
        Index("ix_payment_events_tenant_id_unprocessed", "tenant_id", "created_at"),
    )

    payment_link_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    provider_event_id: Mapped[str] = mapped_column(String(80))
    event_type: Mapped[str] = mapped_column(String(60))
    body_sha256: Mapped[str] = mapped_column(String(64))
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB)
    outcome: Mapped[str | None] = mapped_column(String(20))
    processed_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
