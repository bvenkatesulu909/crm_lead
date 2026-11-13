"""Call recordings (ADR 0030): one row per recording added to a lead.

The row holds the consent record, the status flow and the keys of the stored files; later the
transcript with its timed segments. The database refuses a row without consent, an unknown language
or status, a ``failed`` row without a reason, and a stored status without the file's key (migration
0060). The application role cannot delete rows: a recording is removed by deleting its audio.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantOwnedMixin, UUIDPrimaryKeyMixin
from app.modules.calls import rules

_MAX_BYTES = 524_288_000


class CallRecording(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    __tablename__ = "call_recordings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "lead_id"], ["leads.tenant_id", "leads.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "added_by_user_id"], ["users.tenant_id", "users.id"], ondelete="RESTRICT"
        ),
        CheckConstraint("language IN ('hi', 'te', 'en')", name="language_allowed"),
        CheckConstraint(f"status IN {rules.STATUSES}", name="status_allowed"),
        CheckConstraint(f"declared_size BETWEEN 1 AND {_MAX_BYTES}", name="declared_size_range"),
        CheckConstraint(
            f"size_bytes IS NULL OR size_bytes BETWEEN 1 AND {_MAX_BYTES}", name="size_range"
        ),
        CheckConstraint("(status = 'failed') = (failure_code IS NOT NULL)", name="failed_has_code"),
        CheckConstraint(
            "status NOT IN ('queued', 'processing', 'ready') OR original_key IS NOT NULL",
            name="stored_has_key",
        ),
        CheckConstraint(
            "status <> 'ready' OR transcript_text IS NOT NULL", name="ready_has_transcript"
        ),
        CheckConstraint(
            "transcript_text IS NULL OR char_length(transcript_text) <= 500000",
            name="transcript_length",
        ),
        CheckConstraint(
            "transcript_segments IS NULL OR jsonb_typeof(transcript_segments) = 'array'",
            name="segments_is_list",
        ),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds BETWEEN 0 AND 86400",
            name="duration_range",
        ),
        Index(
            "ix_call_recordings_tenant_id_lead_id_created_at", "tenant_id", "lead_id", "created_at"
        ),
        Index("ix_call_recordings_tenant_id_status", "tenant_id", "status"),
    )

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    added_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    language: Mapped[str] = mapped_column(String(2))
    consent_confirmed_at: Mapped[datetime] = mapped_column()
    file_name: Mapped[str] = mapped_column(String(150))
    content_type: Mapped[str] = mapped_column(String(40))
    declared_size: Mapped[int] = mapped_column(BigInteger)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(12), server_default=text("'uploading'"))
    failure_code: Mapped[str | None] = mapped_column(String(40))
    original_key: Mapped[str | None] = mapped_column(Text)
    clean_key: Mapped[str | None] = mapped_column(Text)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    transcript_text: Mapped[str | None] = mapped_column(Text)
    transcript_segments: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    engine: Mapped[str | None] = mapped_column(String(60))
    audio_deleted_at: Mapped[datetime | None] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column()
