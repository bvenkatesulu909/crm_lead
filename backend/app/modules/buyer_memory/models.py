"""Buyer memory (ADR 0028): one row per thing we recorded about a buyer.

Insert-only: a change adds a row and the newest row of a key is the current one. The database
refuses an UPDATE (a trigger, and the application role has no UPDATE or DELETE privilege) and
refuses a fact without a source and a quote, or an assumption without a reason (migration 0059).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    Identity,
    Index,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantOwnedMixin, UUIDPrimaryKeyMixin
from app.modules.buyer_memory import rules

_KEYS = tuple(k.key for k in rules.KEYS)


class BuyerMemoryItem(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    __tablename__ = "buyer_memory_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "lead_id"], ["leads.tenant_id", "leads.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "recorded_by_user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(f"key IN {_KEYS}", name="key_allowed"),
        CheckConstraint("status IN ('fact', 'assumption')", name="status_allowed"),
        CheckConstraint(f"source IS NULL OR source IN {rules.SOURCES}", name="source_allowed"),
        CheckConstraint("char_length(value) BETWEEN 1 AND 300", name="value_length"),
        CheckConstraint(
            "quote IS NULL OR char_length(quote) BETWEEN 1 AND 300", name="quote_length"
        ),
        CheckConstraint(
            "reason IS NULL OR char_length(reason) BETWEEN 1 AND 300", name="reason_length"
        ),
        CheckConstraint(
            "status <> 'fact' OR (source IS NOT NULL AND quote IS NOT NULL)",
            name="fact_cites_source",
        ),
        CheckConstraint("status <> 'fact' OR reason IS NULL", name="fact_has_no_reason"),
        CheckConstraint(
            "status <> 'assumption' OR reason IS NOT NULL", name="assumption_has_reason"
        ),
        CheckConstraint(
            "status <> 'assumption' OR (source IS NULL AND quote IS NULL AND source_ref IS NULL)",
            name="assumption_has_no_source",
        ),
        CheckConstraint(
            "(source IN ('timeline_entry', 'website_chat')) = (source_ref IS NOT NULL)",
            name="source_ref_matches_source",
        ),
        Index("ix_buyer_memory_items_tenant_id_lead_id_seq", "tenant_id", "lead_id", "seq"),
    )

    # Newest last: rows written in one transaction share created_at.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    recorded_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    key: Mapped[str] = mapped_column(String(30))
    value: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12))
    source: Mapped[str | None] = mapped_column(String(20))
    source_ref: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    quote: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
