"""Visitor conversations of the public website chat (ADR 0013, step PC3).

A conversation is found again only by the SHA-256 hash of its random token (the visitor keeps
the token in an httpOnly cookie on the Next.js server); the visitor's address is kept only as a
keyed hash, for the limits. Neither can be turned back into the original.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
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


class PublicChatDailyStat(Base):
    """Two anonymous numbers per organisation and day (docs/pilot-report.md).

    Conversations that never produced a lead are deleted after a while (privacy), so without
    this the share of chats that end with a lead could not be told afterwards. It holds no
    address, token, text or lead id - only how many conversations started and how many leads
    were saved. The database lets the numbers only grow and never deletes a row.
    """

    __tablename__ = "public_chat_daily_stats"
    __table_args__ = (
        CheckConstraint(
            "conversations_started >= 0 AND leads_saved >= 0", name="counts_not_negative"
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="RESTRICT"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)  # the UTC day
    conversations_started: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    leads_saved: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
