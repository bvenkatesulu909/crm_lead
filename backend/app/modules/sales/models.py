"""Opportunities (deals in the sales pipeline) and their stage history."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
    Identity,
    Index,
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
    SoftDeleteMixin,
    TenantOwnedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    VersionedMixin,
)

OPPORTUNITY_STAGES = (
    "prospecting",
    "qualification",
    "proposal",
    "negotiation",
    "closed_won",
    "closed_lost",
)
OPEN_STAGES = OPPORTUNITY_STAGES[:4]
CLOSED_STAGES = ("closed_won", "closed_lost")
# Chance of winning per stage, used for the weighted (forecast) value. Fixed for now;
# tenant-defined pipelines come with the administration phase.
STAGE_PROBABILITY = {
    "prospecting": 10,
    "qualification": 25,
    "proposal": 50,
    "negotiation": 75,
    "closed_won": 100,
    "closed_lost": 0,
}


class Opportunity(
    UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, SoftDeleteMixin, VersionedMixin, Base
):
    """A potential sale to an account."""

    __tablename__ = "opportunities"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "account_id"], ["accounts.tenant_id", "accounts.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "primary_contact_id"],
            ["contacts.tenant_id", "contacts.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "owner_id"], ["users.tenant_id", "users.id"], ondelete="RESTRICT"
        ),
        CheckConstraint(f"stage IN {OPPORTUNITY_STAGES}", name="stage_allowed"),
        CheckConstraint("amount IS NULL OR amount >= 0", name="amount_not_negative"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso"),
        # Closed (won or lost) exactly when there is a close date; lost deals say why.
        CheckConstraint(
            f"(stage IN {CLOSED_STAGES}) = (closed_at IS NOT NULL)", name="closed_consistent"
        ),
        CheckConstraint(
            "stage <> 'closed_lost' OR lost_reason IS NOT NULL", name="lost_has_reason"
        ),
        Index("ix_opportunities_tenant_id_account_id", "tenant_id", "account_id"),
        Index("ix_opportunities_tenant_id_owner_id", "tenant_id", "owner_id"),
    )

    name: Mapped[str] = mapped_column(String(255))
    account_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    primary_contact_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    stage: Mapped[str] = mapped_column(String(30), server_default=text("'prospecting'"))
    # Money: exact decimal, never float.
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    expected_close_date: Mapped[date | None] = mapped_column(Date)
    closed_at: Mapped[datetime | None] = mapped_column(default=None)
    lost_reason: Mapped[str | None] = mapped_column(String(500))
    next_step: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)

    @property
    def probability(self) -> int:
        return STAGE_PROBABILITY.get(self.stage, 0)

    @property
    def weighted_amount(self) -> Decimal | None:
        if self.amount is None:
            return None
        return (self.amount * self.probability / 100).quantize(Decimal("0.01"))


class OpportunityStageChange(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    """One move of an opportunity through the pipeline (insert-only history)."""

    __tablename__ = "opportunity_stage_changes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "opportunity_id"],
            ["opportunities.tenant_id", "opportunities.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "changed_by_user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            f"from_stage IS NULL OR from_stage IN {OPPORTUNITY_STAGES}", name="from_stage_allowed"
        ),
        CheckConstraint(f"to_stage IN {OPPORTUNITY_STAGES}", name="to_stage_allowed"),
        Index(
            "ix_opportunity_stage_changes_tenant_id_opportunity_id",
            "tenant_id",
            "opportunity_id",
        ),
    )

    opportunity_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    from_stage: Mapped[str | None] = mapped_column(String(30))
    to_stage: Mapped[str] = mapped_column(String(30))
    note: Mapped[str | None] = mapped_column(String(500))
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    changed_at: Mapped[datetime] = mapped_column(server_default=func.clock_timestamp())
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
