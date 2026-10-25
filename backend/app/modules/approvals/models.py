"""Actions an AI proposed, waiting for a person's decision (ADR 0014, step AP1).

A row is history: its status only moves forward (pending -> approved | rejected | expired |
failed) and nothing may delete it. The database itself refuses a decision by the person who
asked for the action.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Index,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import (
    Base,
    TenantOwnedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    VersionedMixin,
)

STATUSES = ("pending", "approved", "rejected", "expired", "failed")
TARGET_TYPES = ("lead", "account", "contact")
AGENTS = ("staff_assistant",)
REASON_MAX = 500


def _user_fk(column: str) -> ForeignKeyConstraint:
    """The person must belong to the same organisation."""
    return ForeignKeyConstraint(
        ["tenant_id", column], ["users.tenant_id", "users.id"], ondelete="RESTRICT"
    )


class AgentAction(UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "agent_actions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        _user_fk("requested_by_user_id"),
        _user_fk("decided_by_user_id"),
        CheckConstraint(f"status IN {STATUSES}", name="status_allowed"),
        CheckConstraint(f"target_type IN {TARGET_TYPES}", name="target_type_allowed"),
        CheckConstraint(f"agent IN {AGENTS}", name="agent_allowed"),
        CheckConstraint("kind ~ '^[a-z_]+\\.[a-z_]+$'", name="kind_shape"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_is_object"),
        CheckConstraint(f"char_length(reason) BETWEEN 1 AND {REASON_MAX}", name="reason_length"),
        # A decision is final and has a time; a pending proposal has neither.
        CheckConstraint("(status = 'pending') = (decided_at IS NULL)", name="decided_when_final"),
        # No self-approval (ADR 0014) - also enforced here, not only in the service.
        CheckConstraint(
            "decided_by_user_id IS NULL OR decided_by_user_id <> requested_by_user_id",
            name="no_self_decision",
        ),
        # The queue: pending proposals of the organisation, soonest expiry first.
        Index("ix_agent_actions_tenant_id_status_expires_at", "tenant_id", "status", "expires_at"),
        # "My proposals" and the per-person pending limit.
        Index(
            "ix_agent_actions_tenant_id_requested_by_user_id_status",
            "tenant_id",
            "requested_by_user_id",
            "status",
        ),
    )

    kind: Mapped[str] = mapped_column(String(50))
    target_type: Mapped[str] = mapped_column(String(20))
    target_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    # Only IDs, codes and short texts, checked against the kind's schema (catalogue.py).
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(String(REASON_MAX))
    agent: Mapped[str] = mapped_column(String(40))
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    decision_note: Mapped[str | None] = mapped_column(String(REASON_MAX), default=None)
    result: Mapped[str | None] = mapped_column(String(REASON_MAX), default=None)
    # Newest first, reliably, even for rows created in the same transaction.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
