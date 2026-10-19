"""Contacts table."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
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

# Kept equal to accounts.models.CONTACT_CHANNELS (modules don't import each other's models).
CONTACT_CHANNELS = ("email", "phone", "mobile", "post", "none")
# E-mail marketing consent: "unknown" until the person says yes or no.
EMAIL_CONSENTS = ("unknown", "granted", "withdrawn")


class Contact(
    UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, SoftDeleteMixin, VersionedMixin, Base
):
    """A person, usually working at a customer account."""

    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        # Account and owner must belong to the SAME tenant as the contact.
        ForeignKeyConstraint(
            ["tenant_id", "account_id"], ["accounts.tenant_id", "accounts.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "owner_id"], ["users.tenant_id", "users.id"], ondelete="RESTRICT"
        ),
        Index("ix_contacts_tenant_id_account_id", "tenant_id", "account_id"),
        Index("ix_contacts_tenant_id_owner_id", "tenant_id", "owner_id"),
        Index("ix_contacts_tenant_id_lower_email", "tenant_id", func.lower(text("email"))),
        Index("ix_contacts_tenant_id_last_name_first_name", "tenant_id", "last_name", "first_name"),
        # At most ONE primary contact per account (archived contacts don't count).
        Index(
            "uq_contacts_one_primary_per_account",
            "tenant_id",
            "account_id",
            unique=True,
            postgresql_where=text("is_primary AND deleted_at IS NULL"),
        ),
        CheckConstraint("NOT is_primary OR account_id IS NOT NULL", name="primary_needs_account"),
        CheckConstraint(
            f"preferred_channel IS NULL OR preferred_channel IN {CONTACT_CHANNELS}",
            name="preferred_channel_allowed",
        ),
        CheckConstraint(f"email_consent IN {EMAIL_CONSENTS}", name="email_consent_allowed"),
        CheckConstraint(
            "preferred_language IS NULL OR preferred_language ~ '^[a-z]{2}$'",
            name="language_iso",
        ),
        # The consent date is set by the server whenever the answer changes.
        CheckConstraint(
            "(email_consent = 'unknown') = (email_consent_at IS NULL)", name="consent_dated"
        ),
    )

    # Not unique on purpose: two real people can share an address (e.g. info@...).
    # Duplicate detection is a business rule in the service layer, not a constraint.
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(50))
    job_title: Mapped[str | None] = mapped_column(String(150))
    account_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    mobile: Mapped[str | None] = mapped_column(String(50))
    department: Mapped[str | None] = mapped_column(String(100))
    is_primary: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    preferred_channel: Mapped[str | None] = mapped_column(String(20))
    email_consent: Mapped[str] = mapped_column(String(20), server_default=text("'unknown'"))
    email_consent_at: Mapped[datetime | None] = mapped_column(default=None)
    do_not_call: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    preferred_language: Mapped[str | None] = mapped_column(String(2))  # ISO 639-1
