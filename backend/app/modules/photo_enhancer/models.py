"""One row per request for an adjusted copy of a photo (ADR 0039, migration 0082).

The row keeps exactly what the person asked for (``operations``) and, once the worker has made the
copy, what was done in plain words (``applied``), its size and the copy itself (a document with
purpose ``property_photo_enhanced``). The database refuses a ``ready`` row without a copy and its
facts, and a ``failed`` row without a reason.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantOwnedMixin, UUIDPrimaryKeyMixin

STATUSES = ("queued", "ready", "failed")


class PhotoEnhancement(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    __tablename__ = "photo_enhancements"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "derived_document_id"),
        CheckConstraint("status IN ('queued', 'ready', 'failed')", name="status_allowed"),
        CheckConstraint("(status = 'failed') = (failure_code IS NOT NULL)", name="failed_has_code"),
        CheckConstraint(
            "(status = 'ready') = (derived_document_id IS NOT NULL)", name="ready_has_copy"
        ),
        CheckConstraint(
            "status <> 'ready' OR (width IS NOT NULL AND height IS NOT NULL "
            "AND size_bytes IS NOT NULL AND applied IS NOT NULL)",
            name="ready_has_facts",
        ),
        CheckConstraint("jsonb_typeof(operations) = 'object'", name="operations_object"),
        CheckConstraint("NOT in_decks OR status = 'ready'", name="deck_only_when_ready"),
        ForeignKeyConstraint(
            ["tenant_id", "original_document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "derived_document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "requested_by_user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
        ),
        Index(
            "ix_photo_enhancements_tenant_id_original_document_id",
            "tenant_id",
            "original_document_id",
        ),
        Index(
            "ix_photo_enhancements_tenant_id_requested_by_user_id_created_at",
            "tenant_id",
            "requested_by_user_id",
            "created_at",
        ),
    )

    original_document_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    derived_document_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(10), server_default="queued")
    failure_code: Mapped[str | None] = mapped_column(String(30), default=None)
    operations: Mapped[dict[str, Any]] = mapped_column(JSONB)
    applied: Mapped[list[str] | None] = mapped_column(JSONB, default=None)
    tool_version: Mapped[str] = mapped_column(String(20))
    width: Mapped[int | None] = mapped_column(Integer, default=None)
    height: Mapped[int | None] = mapped_column(Integer, default=None)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, default=None)
    # The sales person chose this copy for proposal decks (ADR 0039, PE5; migration 0083).
    in_decks: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.clock_timestamp())
    finished_at: Mapped[datetime | None] = mapped_column(default=None)
