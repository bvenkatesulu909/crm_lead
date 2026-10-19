"""Activities table.

One table for both kinds of work:
- a TASK or a planned CALL/MEETING/E-MAIL ("follow-up") is ``open`` with a ``due_at``;
- a LOGGED interaction (a call that happened, a note) is ``done`` with ``completed_at`` = when.

An activity may be linked to ONE record (lead, account, contact or opportunity) or to none
(a personal to-do). Each link is a real foreign key to the same tenant's row.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
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

ACTIVITY_KINDS = ("task", "call", "meeting", "email", "note")
ACTIVITY_STATUSES = ("open", "done", "cancelled")
PRIORITIES = ("low", "normal", "high")
RELATED = ("lead_id", "account_id", "contact_id", "opportunity_id")


def _fk(column: str, table: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["tenant_id", column], [f"{table}.tenant_id", f"{table}.id"], ondelete="RESTRICT"
    )


class Activity(UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "activities"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        _fk("assignee_id", "users"),
        _fk("created_by_user_id", "users"),
        _fk("lead_id", "leads"),
        _fk("account_id", "accounts"),
        _fk("contact_id", "contacts"),
        _fk("opportunity_id", "opportunities"),
        CheckConstraint(f"kind IN {ACTIVITY_KINDS}", name="kind_allowed"),
        CheckConstraint(f"status IN {ACTIVITY_STATUSES}", name="status_allowed"),
        CheckConstraint(f"priority IN {PRIORITIES}", name="priority_allowed"),
        # Linked to at most one record.
        CheckConstraint(
            " + ".join(f"({c} IS NOT NULL)::int" for c in RELATED) + " <= 1",
            name="one_related_record",
        ),
        CheckConstraint("(status = 'done') = (completed_at IS NOT NULL)", name="done_has_time"),
        # A note is a record of something, never a to-do.
        CheckConstraint("kind <> 'note' OR status = 'done'", name="note_is_done"),
        Index(
            "ix_activities_tenant_id_assignee_id_status_due_at",
            "tenant_id",
            "assignee_id",
            "status",
            "due_at",
        ),
        Index("ix_activities_tenant_id_lead_id", "tenant_id", "lead_id"),
        Index("ix_activities_tenant_id_account_id", "tenant_id", "account_id"),
        Index("ix_activities_tenant_id_contact_id", "tenant_id", "contact_id"),
        Index("ix_activities_tenant_id_opportunity_id", "tenant_id", "opportunity_id"),
    )

    kind: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), server_default=text("'open'"))
    priority: Mapped[str] = mapped_column(String(10), server_default=text("'normal'"))
    due_at: Mapped[datetime | None] = mapped_column(default=None)
    reminder_at: Mapped[datetime | None] = mapped_column(default=None)
    # Set by the worker when the reminder was announced (ADR 0006); reset if reminder_at changes.
    reminder_sent_at: Mapped[datetime | None] = mapped_column(default=None)
    completed_at: Mapped[datetime | None] = mapped_column(default=None)
    outcome: Mapped[str | None] = mapped_column(String(500))
    assignee_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    account_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)

    @property
    def overdue(self) -> bool:
        return self.status == "open" and self.due_at is not None and self.due_at < datetime.now(UTC)

    @property
    def related_type(self) -> str | None:
        for column in RELATED:
            if getattr(self, column) is not None:
                return column.removesuffix("_id")
        return None

    @property
    def related_id(self) -> uuid.UUID | None:
        for column in RELATED:
            value: uuid.UUID | None = getattr(self, column)
            if value is not None:
                return value
        return None
