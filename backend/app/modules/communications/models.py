"""E-mail templates and the message history (ADR 0012, step CC1).

A message is one e-mail to (or, logged by hand, from) exactly one lead or one contact. The
recipient and the optional related record are real tenant-scoped foreign keys, one column per
kind of record, so the database itself refuses a message that points at another organisation's
data. Status flow (sending comes with step CC2):

    outbound:        queued ──worker──► sent
                        └──retries used up / address refused──► failed
    inbound_logged:  logged   (typed in by staff; nothing is sent)

Rows are never deleted: the migration takes DELETE away from the application role.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
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

DIRECTIONS = ("outbound", "inbound_logged")
MESSAGE_STATUSES = ("queued", "sent", "failed", "logged")
TEMPLATE_BODY_MAX = 20_000
MESSAGE_BODY_MAX = 50_000


def _fk(column: str, table: str) -> ForeignKeyConstraint:
    """A tenant-scoped reference: the other row must belong to the same organisation."""
    return ForeignKeyConstraint(
        ["tenant_id", column], [f"{table}.tenant_id", f"{table}.id"], ondelete="RESTRICT"
    )


class EmailTemplate(UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, VersionedMixin, Base):
    """A reusable subject + body with placeholders such as ``{{recipient.first_name}}``."""

    __tablename__ = "email_templates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "name"),
        _fk("created_by_user_id", "users"),
        _fk("updated_by_user_id", "users"),
        CheckConstraint("btrim(name) <> ''", name="name_not_blank"),
        CheckConstraint("btrim(subject) <> ''", name="subject_not_blank"),
        CheckConstraint("btrim(body) <> ''", name="body_not_blank"),
        CheckConstraint(f"char_length(body) <= {TEMPLATE_BODY_MAX}", name="body_length"),
    )

    name: Mapped[str] = mapped_column(String(120))
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class EmailMessage(UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, Base):
    __tablename__ = "email_messages"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        _fk("lead_id", "leads"),
        _fk("contact_id", "contacts"),
        _fk("account_id", "accounts"),
        _fk("opportunity_id", "opportunities"),
        _fk("template_id", "email_templates"),
        _fk("sent_by_user_id", "users"),
        CheckConstraint(f"direction IN {DIRECTIONS}", name="direction_allowed"),
        CheckConstraint(f"status IN {MESSAGE_STATUSES}", name="status_allowed"),
        CheckConstraint(
            "(direction = 'inbound_logged') = (status = 'logged')", name="logged_means_inbound"
        ),
        CheckConstraint("(lead_id IS NULL) <> (contact_id IS NULL)", name="one_recipient"),
        CheckConstraint("account_id IS NULL OR opportunity_id IS NULL", name="one_related_record"),
        CheckConstraint(
            "lead_id IS NULL OR (account_id IS NULL AND opportunity_id IS NULL)",
            name="lead_has_no_related_record",
        ),
        CheckConstraint("(status = 'sent') = (sent_at IS NOT NULL)", name="sent_has_time"),
        CheckConstraint("status = 'failed' OR error_code IS NULL", name="error_only_if_failed"),
        # A coarse shape check; the real address always comes from the lead or contact record.
        CheckConstraint("to_address ~ '^[^@\\s]+@[^@\\s]+$'", name="address_shape"),
        CheckConstraint("btrim(subject) <> ''", name="subject_not_blank"),
        CheckConstraint("btrim(body) <> ''", name="body_not_blank"),
        CheckConstraint(f"char_length(body) <= {MESSAGE_BODY_MAX}", name="body_length"),
        Index("ix_email_messages_tenant_id_lead_id", "tenant_id", "lead_id"),
        Index("ix_email_messages_tenant_id_contact_id", "tenant_id", "contact_id"),
        Index("ix_email_messages_tenant_id_account_id", "tenant_id", "account_id"),
        Index("ix_email_messages_tenant_id_opportunity_id", "tenant_id", "opportunity_id"),
        # The "own" list and the hourly sending limit both look up one sender's newest e-mails.
        Index(
            "ix_email_messages_tenant_id_sent_by_user_id_created_at",
            "tenant_id",
            "sent_by_user_id",
            "created_at",
        ),
        Index("ix_email_messages_tenant_id_created_at", "tenant_id", "created_at"),
    )

    direction: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    account_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    to_address: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    template_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    # Who wrote the e-mail, or who logged a received one.
    sent_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    sent_at: Mapped[datetime | None] = mapped_column(default=None)
    # A short machine code when sending failed (e.g. "recipient_refused"), never the server's
    # full answer, which may contain personal data.
    error_code: Mapped[str | None] = mapped_column(String(60))
