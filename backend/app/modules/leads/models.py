"""Lead tables: ``leads``, ``lead_activities`` (timeline) and ``lead_assignments`` (history)."""

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

LEAD_STATUSES = ("new", "contacted", "qualified", "unqualified", "converted")
# Activities a user records by hand ...
USER_ACTIVITY_KINDS = ("note", "call", "email", "meeting")
# ... and ones the system writes automatically when something happens to the lead.
SYSTEM_ACTIVITY_KINDS = ("created", "status_changed", "assigned", "converted")
ACTIVITY_KINDS = USER_ACTIVITY_KINDS + SYSTEM_ACTIVITY_KINDS


class Lead(
    UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, SoftDeleteMixin, VersionedMixin, Base
):
    """A potential customer. Conversion turns it into an account + contact (+ opportunity)."""

    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "owner_id"], ["users.tenant_id", "users.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "converted_account_id"],
            ["accounts.tenant_id", "accounts.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "converted_contact_id"],
            ["contacts.tenant_id", "contacts.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "converted_opportunity_id"],
            ["opportunities.tenant_id", "opportunities.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(f"status IN {LEAD_STATUSES}", name="status_allowed"),
        # "converted" and the conversion timestamp always go together.
        CheckConstraint(
            "(status = 'converted') = (converted_at IS NOT NULL)", name="converted_consistent"
        ),
        # A converted lead always points at the account and contact it became.
        CheckConstraint(
            "status <> 'converted' OR "
            "(converted_account_id IS NOT NULL AND converted_contact_id IS NOT NULL)",
            name="converted_has_records",
        ),
        Index("ix_leads_tenant_id_status", "tenant_id", "status"),
        Index("ix_leads_tenant_id_owner_id", "tenant_id", "owner_id"),
        Index("ix_leads_tenant_id_lower_email", "tenant_id", func.lower(text("email"))),
        Index("ix_leads_tenant_id_created_at", "tenant_id", "created_at"),
    )

    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    company_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(50))
    job_title: Mapped[str | None] = mapped_column(String(150))
    status: Mapped[str] = mapped_column(String(20), server_default=text("'new'"))
    source: Mapped[str | None] = mapped_column(String(50))
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    converted_at: Mapped[datetime | None] = mapped_column(default=None)
    converted_account_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    converted_contact_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    converted_opportunity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class LeadActivity(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    """One entry on a lead's timeline (a call, a note, a status change, ...)."""

    __tablename__ = "lead_activities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "lead_id"], ["leads.tenant_id", "leads.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "actor_user_id"], ["users.tenant_id", "users.id"], ondelete="RESTRICT"
        ),
        CheckConstraint(f"kind IN {ACTIVITY_KINDS}", name="kind_allowed"),
        Index(
            "ix_lead_activities_tenant_id_lead_id_occurred_at",
            "tenant_id",
            "lead_id",
            "occurred_at",
        ),
    )

    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    # clock_timestamp(): the real insert time. (now() would be the transaction start, giving
    # several events of one request the same time.)
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.clock_timestamp())
    # Ever-increasing number: a stable tie-breaker so the timeline order is always exact.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class LeadAssignment(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    """History of who owned a lead, who changed it and why. Rows are only ever added."""

    __tablename__ = "lead_assignments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "lead_id"], ["leads.tenant_id", "leads.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "from_user_id"], ["users.tenant_id", "users.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "to_user_id"], ["users.tenant_id", "users.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "assigned_by_user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
        ),
        Index(
            "ix_lead_assignments_tenant_id_lead_id_assigned_at",
            "tenant_id",
            "lead_id",
            "assigned_at",
        ),
    )

    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    from_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    to_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    assigned_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reason: Mapped[str | None] = mapped_column(String(500))
    assigned_at: Mapped[datetime] = mapped_column(server_default=func.clock_timestamp())
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
