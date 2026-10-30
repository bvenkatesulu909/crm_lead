"""Evidence of a web check (ADR 0019).

One row per finished check: what was asked, of which source, who asked, what came back (parsed
and cleaned) and a hash of the page. Insert-only: the database refuses to change a row, and
refuses to delete one younger than the retention (migration 0045).
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantOwnedMixin, UUIDPrimaryKeyMixin

VERDICTS = ("found", "not_found", "unclear", "error")
TARGET_TYPES = ("lead", "account")


class WebEvidence(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    __tablename__ = "web_evidence"
    __table_args__ = (
        UniqueConstraint("tenant_id", "request_id"),
        ForeignKeyConstraint(
            ["tenant_id", "requested_by_user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(f"verdict IN {VERDICTS}", name="verdict_allowed"),
        CheckConstraint(f"target_type IN {TARGET_TYPES}", name="target_type_allowed"),
        # An error says which kind; nothing else carries an error code.
        CheckConstraint("(verdict = 'error') = (error_code IS NOT NULL)", name="error_has_code"),
        CheckConstraint("char_length(excerpt) <= 4096", name="excerpt_length"),
        CheckConstraint("char_length(query) BETWEEN 1 AND 200", name="query_length"),
        CheckConstraint("source_key ~ '^[a-z][a-z0-9_]{2,59}$'", name="source_key_shape"),
        CheckConstraint(
            "body_sha256 IS NULL OR body_sha256 ~ '^[0-9a-f]{64}$'", name="body_sha256_shape"
        ),
        CheckConstraint("jsonb_typeof(cleaned) = 'array'", name="cleaned_is_list"),
        Index("ix_web_evidence_tenant_id_target", "tenant_id", "target_type", "target_id", "seq"),
    )

    # Newest first: rows written in one transaction share created_at.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # The id the person got when they asked; it ties the evidence to the request.
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    target_type: Mapped[str] = mapped_column(String(20))
    target_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    source_key: Mapped[str] = mapped_column(String(60))
    query: Mapped[str] = mapped_column(String(200))
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    verdict: Mapped[str] = mapped_column(String(20))
    error_code: Mapped[str | None] = mapped_column(String(60))
    http_status: Mapped[int | None] = mapped_column(Integer)
    final_url: Mapped[str | None] = mapped_column(Text)
    body_sha256: Mapped[str | None] = mapped_column(String(64))
    registered_name: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str | None] = mapped_column(String(40))
    valid_until: Mapped[date | None] = mapped_column(Date)
    excerpt: Mapped[str] = mapped_column(Text, server_default=text("''"))
    # The kinds of finding when text had to be cleaned (never the removed text).
    cleaned: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
