"""Notification tables (ADR 0006)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantOwnedMixin, UUIDPrimaryKeyMixin


class Notification(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    """One message for one person, e.g. "A lead was assigned to you"."""

    __tablename__ = "notifications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], ondelete="CASCADE"
        ),
        # One notification per person per event: the worker may deliver an event twice.
        UniqueConstraint("tenant_id", "user_id", "event_id"),
        Index("ix_notifications_tenant_user_created", "tenant_id", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    type: Mapped[str] = mapped_column(String(50))  # the event name, e.g. "lead.assigned"
    title: Mapped[str] = mapped_column(String(300))
    link: Mapped[str] = mapped_column(String(300))  # a page inside the CRM, e.g. /leads/<id>
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(default=None)


class NotificationPreference(Base):
    """Per person and notification type: also send an e-mail? (In-app is always on.)"""

    __tablename__ = "notification_preferences"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], ondelete="CASCADE"
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    type: Mapped[str] = mapped_column(String(50), primary_key=True)
    email: Mapped[bool] = mapped_column(Boolean)
