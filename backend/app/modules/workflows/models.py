"""Workflow rules and their run log (ADR 0006, step 17b)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
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

from app.core.models import (
    Base,
    TenantOwnedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    VersionedMixin,
)

RUN_STATUSES = ("done", "failed", "limited")


class WorkflowRule(UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "workflow_rules"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("days IS NULL OR (days >= 0 AND days <= 365)", name="days_range"),
        Index("ix_workflow_rules_tenant_id_trigger", "tenant_id", "trigger"),
    )

    name: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    trigger: Mapped[str] = mapped_column(String(50))
    days: Mapped[int | None] = mapped_column(Integer, default=None)
    # Always the normalised shape from rules.validate().
    conditions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    actions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)


class WorkflowRun(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    """One time a rule's conditions matched: what happened (or why nothing did)."""

    __tablename__ = "workflow_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "rule_id"],
            ["workflow_rules.tenant_id", "workflow_rules.id"],
            ondelete="CASCADE",
        ),
        # A rule acts at most once per event (or per record and date for schedules).
        UniqueConstraint("tenant_id", "rule_id", "run_key"),
        CheckConstraint("status IN ('done', 'failed', 'limited')", name="status_allowed"),
        Index("ix_workflow_runs_tenant_id_created_at", "tenant_id", "created_at"),
    )

    rule_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    run_key: Mapped[str] = mapped_column(String(150))
    record_type: Mapped[str] = mapped_column(String(20))
    record_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    record_label: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20))
    message: Mapped[str | None] = mapped_column(String(500), default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
