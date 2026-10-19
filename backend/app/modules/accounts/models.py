"""Accounts table."""

import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    String,
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

ACCOUNT_STATUSES = ("active", "inactive")
# Customer segmentation. A fixed list for now; tenant-defined master data comes with Admin.
ACCOUNT_SEGMENTS = ("enterprise", "mid_market", "small_business", "public_sector", "non_profit")
# Where the customer is in its relationship with us (set by staff; "at risk" is also
# suggested by the health indicator).
LIFECYCLE_STAGES = ("prospect", "onboarding", "active_customer", "at_risk", "churned")
# Place in a company group (the parent link says which group).
ACCOUNT_TYPES = ("company", "headquarters", "subsidiary", "branch")
# How the customer prefers to be contacted (shared with contacts).
CONTACT_CHANNELS = ("email", "phone", "mobile", "post", "none")


class Account(
    UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, SoftDeleteMixin, VersionedMixin, Base
):
    """A customer organisation of the tenant."""

    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        # Optional external/ERP number; unique within the tenant when present.
        UniqueConstraint("tenant_id", "account_number"),
        # Owner must be a user of the SAME tenant.
        ForeignKeyConstraint(
            ["tenant_id", "owner_id"], ["users.tenant_id", "users.id"], ondelete="RESTRICT"
        ),
        # Parent account (company hierarchy) must belong to the SAME tenant.
        ForeignKeyConstraint(
            ["tenant_id", "parent_account_id"],
            ["accounts.tenant_id", "accounts.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "parent_account_id IS NULL OR parent_account_id <> id", name="not_own_parent"
        ),
        CheckConstraint(f"status IN {ACCOUNT_STATUSES}", name="status_allowed"),
        CheckConstraint(
            f"segment IS NULL OR segment IN {ACCOUNT_SEGMENTS}", name="segment_allowed"
        ),
        CheckConstraint(
            f"preferred_channel IS NULL OR preferred_channel IN {CONTACT_CHANNELS}",
            name="preferred_channel_allowed",
        ),
        CheckConstraint(
            f"lifecycle_stage IS NULL OR lifecycle_stage IN {LIFECYCLE_STAGES}",
            name="lifecycle_stage_allowed",
        ),
        CheckConstraint(f"account_type IN {ACCOUNT_TYPES}", name="account_type_allowed"),
        CheckConstraint("country IS NULL OR country ~ '^[A-Z]{2}$'", name="country_iso"),
        CheckConstraint(
            "preferred_language IS NULL OR preferred_language ~ '^[a-z]{2}$'",
            name="language_iso",
        ),
        Index("ix_accounts_tenant_id_country", "tenant_id", "country"),
        Index("ix_accounts_tenant_id_lower_name", "tenant_id", func.lower(text("name"))),
        Index("ix_accounts_tenant_id_owner_id", "tenant_id", "owner_id"),
        Index("ix_accounts_tenant_id_parent_account_id", "tenant_id", "parent_account_id"),
    )

    name: Mapped[str] = mapped_column(String(255))
    account_number: Mapped[str | None] = mapped_column(String(50))
    website: Mapped[str | None] = mapped_column(String(2048))
    industry: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), server_default=text("'active'"))
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    parent_account_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    segment: Mapped[str | None] = mapped_column(String(30))
    preferred_channel: Mapped[str | None] = mapped_column(String(20))
    country: Mapped[str | None] = mapped_column(String(2))  # ISO 3166-1 alpha-2, e.g. DE
    region: Mapped[str | None] = mapped_column(String(100))  # state / province / county
    city: Mapped[str | None] = mapped_column(String(100))
    lifecycle_stage: Mapped[str | None] = mapped_column(String(20))
    account_type: Mapped[str] = mapped_column(String(20), server_default=text("'company'"))
    preferred_language: Mapped[str | None] = mapped_column(String(2))  # ISO 639-1, e.g. en
