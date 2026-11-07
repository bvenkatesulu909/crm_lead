"""The staff assistant's short conversation memory (ADR 0023, step VM1).

- ``staff_assistant_conversations``: one conversation of one employee with the staff assistant.
- ``staff_assistant_turns``: what the employee asked (after input screening) and what the
  assistant answered (after exit cleaning). Only the last few turns are given to the model again.

Both are short-lived: the worker deletes a conversation (and its turns) once it has been quiet for
``CRM_STAFF_CONVERSATION_RETENTION_HOURS`` (24). No audio is ever stored - only text.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
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

TURN_ROLES = ("user", "assistant")
MAX_TURN_CHARS = 8000


class StaffConversation(UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, Base):
    __tablename__ = "staff_assistant_conversations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], ondelete="RESTRICT"
        ),
        CheckConstraint("turn_count >= 0", name="turn_count_not_negative"),
        Index("ix_staff_assistant_conversations_tenant_id_user_id", "tenant_id", "user_id"),
        Index("ix_staff_assistant_conversations_last_turn_at", "last_turn_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    last_turn_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    turn_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class StaffTurn(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    __tablename__ = "staff_assistant_turns"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["staff_assistant_conversations.tenant_id", "staff_assistant_conversations.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("role IN ('user', 'assistant')", name="role_allowed"),
        CheckConstraint(f"char_length(content) <= {MAX_TURN_CHARS}", name="content_length"),
        Index(
            "ix_staff_assistant_turns_tenant_id_conversation_id_seq",
            "tenant_id",
            "conversation_id",
            "seq",
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.clock_timestamp())
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
