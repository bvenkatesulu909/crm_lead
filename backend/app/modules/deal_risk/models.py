"""One stored deal risk snapshot (ADR 0037, step DR2).

Insert-only: the database refuses to change a row and to delete one younger than 365 days
(migration 0073). The factors are stored as codes, sentences and numbers - never free text a person
typed - so a snapshot can be shown again without reading the deal.
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
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantOwnedMixin, UUIDPrimaryKeyMixin


class DealRiskSnapshot(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    __tablename__ = "deal_risk_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "opportunity_id"],
            ["opportunities.tenant_id", "opportunities.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "requested_by_user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("level IN ('low', 'medium', 'high')", name="level_allowed"),
        CheckConstraint("score BETWEEN 0 AND 100", name="score_range"),
        CheckConstraint("rules_version >= 1", name="rules_version_positive"),
        CheckConstraint("source IN ('nightly', 'on_demand')", name="source_allowed"),
        CheckConstraint(
            "(source = 'nightly') = (requested_by_user_id IS NULL)", name="asker_matches_source"
        ),
        CheckConstraint("jsonb_typeof(factors) = 'array'", name="factors_is_list"),
        CheckConstraint("jsonb_typeof(unknown) = 'array'", name="unknown_is_list"),
        Index(
            "ix_deal_risk_snapshots_tenant_id_opportunity_id", "tenant_id", "opportunity_id", "seq"
        ),
        Index("ix_deal_risk_snapshots_tenant_id_created_at", "tenant_id", "created_at"),
    )

    # Newest first: rows written in one transaction would share a plain timestamp.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
    created_at: Mapped[datetime] = mapped_column(server_default=func.clock_timestamp())
    opportunity_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    level: Mapped[str] = mapped_column(String(10))
    score: Mapped[int] = mapped_column(Integer)
    rules_version: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(12))
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    # [{"code", "sentence", "points", "source"}]
    factors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    # Signals that could not be read, as codes.
    unknown: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
