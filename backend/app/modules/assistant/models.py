"""Assistant tables (ADR 0003).

- ``assistant_conversations``: one chat of one customer user.
- ``assistant_messages``: what the customer wrote and what the assistant answered. Insert-only.
- ``assistant_tool_calls``: AUDIT of every tool the model asked for, with the (shortened)
  arguments and whether it was allowed. Insert-only.
- ``assistant_pending_actions``: actions the model may only PROPOSE (today: open a support
  ticket). Nothing happens until the customer confirms in the portal.
"""

import uuid
from datetime import datetime
from typing import Any

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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantOwnedMixin, TimestampMixin, UUIDPrimaryKeyMixin

MESSAGE_ROLES = ("user", "assistant")
TOOL_OUTCOMES = ("ok", "not_found", "invalid", "refused", "error")
ACTION_KINDS = ("create_ticket",)
ACTION_STATUSES = ("pending", "confirmed", "cancelled")


def _user_fk(column: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["tenant_id", column], ["users.tenant_id", "users.id"], ondelete="RESTRICT"
    )


def _conversation_fk() -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["tenant_id", "conversation_id"],
        ["assistant_conversations.tenant_id", "assistant_conversations.id"],
        ondelete="RESTRICT",
    )


class Conversation(UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, Base):
    __tablename__ = "assistant_conversations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        _user_fk("user_id"),
        Index("ix_assistant_conversations_tenant_id_user_id", "tenant_id", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(120))


class Message(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    __tablename__ = "assistant_messages"
    __table_args__ = (
        _conversation_fk(),
        CheckConstraint(f"role IN {MESSAGE_ROLES}", name="role_allowed"),
        Index(
            "ix_assistant_messages_tenant_id_conversation_id_seq",
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


class ToolCall(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    __tablename__ = "assistant_tool_calls"
    __table_args__ = (
        _conversation_fk(),
        _user_fk("user_id"),
        CheckConstraint(f"outcome IN {TOOL_OUTCOMES}", name="outcome_allowed"),
        Index(
            "ix_assistant_tool_calls_tenant_id_conversation_id_seq",
            "tenant_id",
            "conversation_id",
            "seq",
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    tool_name: Mapped[str] = mapped_column(String(64))
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB)
    outcome: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(server_default=func.clock_timestamp())
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))


class PendingAction(UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, Base):
    __tablename__ = "assistant_pending_actions"
    __table_args__ = (
        _conversation_fk(),
        _user_fk("user_id"),
        CheckConstraint(
            "kind IN (" + ", ".join(f"'{k}'" for k in ACTION_KINDS) + ")", name="kind_allowed"
        ),
        CheckConstraint(f"status IN {ACTION_STATUSES}", name="status_allowed"),
        CheckConstraint(
            "(status = 'confirmed') = (result_id IS NOT NULL)", name="result_consistent"
        ),
        Index(
            "ix_assistant_pending_actions_tenant_id_conversation_id", "tenant_id", "conversation_id"
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), server_default=text("'pending'"))
    # The created record (e.g. the ticket) once confirmed.
    result_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
