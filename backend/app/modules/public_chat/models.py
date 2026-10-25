"""Visitor conversations of the public website chat (ADR 0013, step PC3).

A conversation is found again only by the SHA-256 hash of its random token (the visitor keeps
the token in an httpOnly cookie on the Next.js server); the visitor's address is kept only as a
keyed hash, for the limits. Neither can be turned back into the original.
"""

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
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantOwnedMixin, TimestampMixin, UUIDPrimaryKeyMixin

ROLES = ("visitor", "assistant")
MESSAGE_MAX = 8000


class PublicChatSession(UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, Base):
    __tablename__ = "public_chat_sessions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "token_hash"),
        ForeignKeyConstraint(
            ["tenant_id", "lead_id"], ["leads.tenant_id", "leads.id"], ondelete="RESTRICT"
        ),
        CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="token_hash_shape"),
        CheckConstraint("visitor_ip_hash ~ '^[0-9a-f]{64}$'", name="ip_hash_shape"),
        # The limits look up one address's newest conversations.
        Index(
            "ix_public_chat_sessions_tenant_id_visitor_ip_hash_created_at",
            "tenant_id",
            "visitor_ip_hash",
            "created_at",
        ),
    )

    token_hash: Mapped[str] = mapped_column(String(64))
    visitor_ip_hash: Mapped[str] = mapped_column(String(64))
    # The lead this conversation produced (at most one, ADR 0013).
    lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class PublicChatMessage(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    __tablename__ = "public_chat_messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "session_id"],
            ["public_chat_sessions.tenant_id", "public_chat_sessions.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(f"role IN {ROLES}", name="role_allowed"),
        CheckConstraint(f"char_length(content) <= {MESSAGE_MAX}", name="content_length"),
        Index("ix_public_chat_messages_tenant_id_session_id_seq", "tenant_id", "session_id", "seq"),
        # The daily ceiling counts the organisation's visitor messages since yesterday.
        Index("ix_public_chat_messages_tenant_id_created_at", "tenant_id", "created_at"),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.clock_timestamp())
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
