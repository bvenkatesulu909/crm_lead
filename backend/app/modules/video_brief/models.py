"""Saved video scripts (ADR 0041, VB3).

One row per saved version of a lead's script: the lines, the choices they were written for, who
saved them. Insert-only: the database refuses to change a row and to delete one younger than 365
days (migration 0075). The newest version of a lead is the current one. ``source`` is
``hand_written`` now; an approved AI draft (VB5) will be ``ai_draft``.
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
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantOwnedMixin, UUIDPrimaryKeyMixin


class VideoScript(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    __tablename__ = "video_scripts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "lead_id"], ["leads.tenant_id", "leads.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "proposal_id"],
            ["agent_actions.tenant_id", "agent_actions.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "lead_id", "version"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("language IN ('en', 'hi', 'te')", name="language_allowed"),
        CheckConstraint("tone IN ('warm', 'professional', 'brisk')", name="tone_allowed"),
        CheckConstraint(
            "goal IN ('introduce', 'follow_up', 'after_visit', 'explain_quote', 'revive')",
            name="goal_allowed",
        ),
        CheckConstraint("length_seconds IN (30, 60, 90)", name="length_allowed"),
        CheckConstraint("source IN ('hand_written', 'ai_draft')", name="source_allowed"),
        CheckConstraint("words >= 1", name="words_positive"),
        CheckConstraint(
            "(source = 'ai_draft') = (proposal_id IS NOT NULL)", name="proposal_matches_source"
        ),
        CheckConstraint("jsonb_array_length(lines) BETWEEN 1 AND 12", name="lines_count"),
        Index("ix_video_scripts_tenant_id_lead_id", "tenant_id", "lead_id", "seq"),
    )

    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer)
    language: Mapped[str] = mapped_column(String(2))
    tone: Mapped[str] = mapped_column(String(20))
    goal: Mapped[str] = mapped_column(String(20))
    length_seconds: Mapped[int] = mapped_column(Integer)
    lines: Mapped[list[Any]] = mapped_column(JSONB)
    words: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(20))
    # The approved proposal an AI draft came from (ADR 0041, VB5); none for a hand-written script.
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
