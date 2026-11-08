"""A stored deal review (ADR 0024, step DD2).

One row per finished review: the deal, who asked, the desk lead's brief, every reviewer's findings
(each with the records it cites), which reviewers answered, the proposals it made and the tokens it
used. Insert-only: the database refuses to change a row and to delete one younger than 365 days
(migration 0052).
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
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantOwnedMixin, UUIDPrimaryKeyMixin

BRIEF_MAX = 1200


class DealReview(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    __tablename__ = "deal_reviews"
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
        CheckConstraint(f"char_length(brief) BETWEEN 1 AND {BRIEF_MAX}", name="brief_length"),
        CheckConstraint("jsonb_typeof(findings) = 'array'", name="findings_is_list"),
        CheckConstraint("jsonb_typeof(reviewers) = 'object'", name="reviewers_is_object"),
        CheckConstraint("jsonb_typeof(proposal_ids) = 'array'", name="proposal_ids_is_list"),
        CheckConstraint("input_tokens >= 0 AND output_tokens >= 0", name="tokens_not_negative"),
        Index("ix_deal_reviews_tenant_id_opportunity_id", "tenant_id", "opportunity_id", "seq"),
    )

    # Newest first: rows written in one transaction share created_at.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    opportunity_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    brief: Mapped[str] = mapped_column(Text)
    # [{"reviewer", "severity", "text", "record_ids": [...]}]
    findings: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    # {"pricing": "answered" | "refused", ...}
    reviewers: Mapped[dict[str, str]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    proposal_ids: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    input_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class AccountBrief(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    """One account brief (ADR 0024, step DD4): the writer's cited sentences, how many sentences
    were removed for citing nothing gathered, how many facts each gatherer found, and the tokens.
    Insert-only like ``deal_reviews`` (migration 0053)."""

    __tablename__ = "account_briefs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "account_id"], ["accounts.tenant_id", "accounts.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "requested_by_user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("jsonb_typeof(sentences) = 'array'", name="sentences_is_list"),
        CheckConstraint("jsonb_typeof(gathered) = 'object'", name="gathered_is_object"),
        CheckConstraint("dropped >= 0", name="dropped_not_negative"),
        CheckConstraint("input_tokens >= 0 AND output_tokens >= 0", name="tokens_not_negative"),
        Index("ix_account_briefs_tenant_id_account_id", "tenant_id", "account_id", "seq"),
    )

    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    account_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    # [{"text", "records": [{"type", "id"}]}]
    sentences: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    dropped: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # {"sales": 4, "service": 2, ...}: how many facts each gatherer found
    gathered: Mapped[dict[str, int]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    input_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
