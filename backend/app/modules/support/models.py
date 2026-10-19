"""Support tables: ``tickets``, ``ticket_comments`` and ``ticket_number_counters``."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    SmallInteger,
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

TICKET_STATUSES = ("new", "open", "pending_customer", "resolved", "closed")
TICKET_PRIORITIES = ("low", "normal", "high", "urgent")
# Where the ticket came from. "assistant" = handed over to a human by the AI assistant.
TICKET_CHANNELS = ("portal", "staff", "assistant")
# What kind of contact this is; "complaint" is reported separately (customer feedback).
TICKET_CATEGORIES = ("question", "problem", "request", "complaint", "feedback")
COMMENT_VISIBILITIES = ("public", "internal")


class Ticket(UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, VersionedMixin, Base):
    """A customer's support request about one of their accounts."""

    __tablename__ = "tickets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        # Human-friendly number, unique within the tenant (T-0001, T-0002, ...).
        UniqueConstraint("tenant_id", "number"),
        ForeignKeyConstraint(
            ["tenant_id", "account_id"], ["accounts.tenant_id", "accounts.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "requester_user_id"], ["users.tenant_id", "users.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "assignee_user_id"], ["users.tenant_id", "users.id"], ondelete="RESTRICT"
        ),
        CheckConstraint(f"status IN {TICKET_STATUSES}", name="status_allowed"),
        CheckConstraint(f"priority IN {TICKET_PRIORITIES}", name="priority_allowed"),
        CheckConstraint(f"channel IN {TICKET_CHANNELS}", name="channel_allowed"),
        CheckConstraint(f"category IN {TICKET_CATEGORIES}", name="category_allowed"),
        # Customer satisfaction: 1 (very unhappy) .. 5 (very happy), given once resolved.
        CheckConstraint(
            "satisfaction_rating IS NULL OR satisfaction_rating BETWEEN 1 AND 5",
            name="rating_range",
        ),
        CheckConstraint("(satisfaction_rating IS NULL) = (rated_at IS NULL)", name="rating_dated"),
        CheckConstraint("(status = 'closed') = (closed_at IS NOT NULL)", name="closed_consistent"),
        CheckConstraint("number > 0", name="number_positive"),
        Index("ix_tickets_tenant_id_status", "tenant_id", "status"),
        Index("ix_tickets_tenant_id_account_id", "tenant_id", "account_id"),
        Index("ix_tickets_tenant_id_assignee_user_id", "tenant_id", "assignee_user_id"),
        Index("ix_tickets_tenant_id_created_at", "tenant_id", "created_at"),
    )

    number: Mapped[int] = mapped_column(Integer)
    account_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    requester_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    subject: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), server_default=text("'new'"))
    priority: Mapped[str] = mapped_column(String(10), server_default=text("'normal'"))
    channel: Mapped[str] = mapped_column(String(10))
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    # SLA targets (set at creation from the priority) and the moments they were met.
    first_response_due_at: Mapped[datetime]
    resolution_due_at: Mapped[datetime]
    first_responded_at: Mapped[datetime | None] = mapped_column(default=None)
    resolved_at: Mapped[datetime | None] = mapped_column(default=None)
    closed_at: Mapped[datetime | None] = mapped_column(default=None)
    category: Mapped[str] = mapped_column(String(20), server_default=text("'question'"))
    satisfaction_rating: Mapped[int | None] = mapped_column(SmallInteger)
    satisfaction_comment: Mapped[str | None] = mapped_column(String(1000))
    rated_at: Mapped[datetime | None] = mapped_column(default=None)


class TicketComment(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    """A message on a ticket. "internal" notes are never shown to customers.
    Append-only: the application cannot edit or delete comments (see migration 0004)."""

    __tablename__ = "ticket_comments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ticket_id"], ["tickets.tenant_id", "tickets.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "author_user_id"], ["users.tenant_id", "users.id"], ondelete="RESTRICT"
        ),
        CheckConstraint(f"visibility IN {COMMENT_VISIBILITIES}", name="visibility_allowed"),
        Index("ix_ticket_comments_tenant_id_ticket_id_seq", "tenant_id", "ticket_id", "seq"),
    )

    ticket_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    body: Mapped[str] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(server_default=func.clock_timestamp())
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))


class TicketNumberCounter(Base):
    """Last ticket number used per tenant (incremented atomically, see repository)."""

    __tablename__ = "ticket_number_counters"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="RESTRICT"), primary_key=True
    )
    last_number: Mapped[int] = mapped_column(Integer)
