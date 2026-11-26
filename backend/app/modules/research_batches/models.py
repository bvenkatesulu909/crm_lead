"""Batch account research (ADR 0042, BR1): a batch row and one row per account in it.

Both tables are append-mostly. The people and the numbers that decide what a batch may do (starter,
cap, account list, positions) can never change after creation - a trigger refuses it - and only the
progress columns move. A row cannot be deleted before it is 365 days old (the same retention as
account briefs) and the application role cannot truncate either table.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantOwnedMixin, UUIDPrimaryKeyMixin, VersionedMixin
from app.modules.research_batches import rules


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


class ResearchBatch(UUIDPrimaryKeyMixin, TenantOwnedMixin, VersionedMixin, Base):
    __tablename__ = "research_batches"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(_in_list("status", rules.BATCH_STATUSES), name="status_allowed"),
        CheckConstraint(_in_list("source", rules.SOURCES), name="source_allowed"),
        CheckConstraint(
            f"account_count BETWEEN 1 AND {rules.MAX_BATCH}", name="account_count_range"
        ),
        CheckConstraint("token_cap >= 0 AND tokens_used >= 0", name="tokens_not_negative"),
        CheckConstraint("estimated_upper_tokens >= 0", name="estimate_not_negative"),
        CheckConstraint(
            "(status = 'running') = (finished_at IS NULL)", name="finished_matches_status"
        ),
        Index(
            "ix_research_batches_tenant_id_created_by_user_id", "tenant_id", "created_by_user_id"
        ),
        Index("ix_research_batches_tenant_id_status", "tenant_id", "status"),
    )

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(20), server_default=text("'running'"))
    # 'filter' = a saved filter, 'rows' = ticked rows. The filter id is kept for reference only: a
    # filter can be deleted later, and the batch holds its own frozen list of accounts.
    source: Mapped[str] = mapped_column(String(10))
    saved_filter_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    account_count: Mapped[int] = mapped_column(Integer)
    not_available_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    archived_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # What the person was shown and confirmed, and the hard cap built from it (BR7).
    estimated_upper_tokens: Mapped[int] = mapped_column(BigInteger)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), default=None)
    token_cap: Mapped[int] = mapped_column(BigInteger)
    tokens_used: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    research_again: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    finished_at: Mapped[datetime | None] = mapped_column(default=None)


class ResearchBatchItem(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    __tablename__ = "research_batch_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["research_batches.tenant_id", "research_batches.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "account_id"], ["accounts.tenant_id", "accounts.id"], ondelete="RESTRICT"
        ),
        UniqueConstraint("batch_id", "position"),
        UniqueConstraint("batch_id", "account_id"),
        CheckConstraint(_in_list("status", rules.ITEM_STATUSES), name="status_allowed"),
        CheckConstraint(f"position BETWEEN 1 AND {rules.MAX_BATCH}", name="position_range"),
        CheckConstraint(
            "(status = 'failed') = (failure_code IS NOT NULL) AND "
            f"(failure_code IS NULL OR {_in_list('failure_code', rules.FAILURE_CODES)})",
            name="failure_matches_status",
        ),
        CheckConstraint(
            "(brief_id IS NOT NULL) = (status IN ('done', 'reused'))",
            name="brief_matches_status",
        ),
        CheckConstraint("input_tokens >= 0 AND output_tokens >= 0", name="tokens_not_negative"),
        Index("ix_research_batch_items_tenant_id_batch_id", "tenant_id", "batch_id", "position"),
    )

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    batch_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    position: Mapped[int] = mapped_column(Integer)
    account_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(10), server_default=text("'queued'"))
    failure_code: Mapped[str | None] = mapped_column(String(30), default=None)
    # The brief this item produced or reused. No foreign key: briefs belong to the deal desk module
    # and the service checks the id; a brief can only be deleted after 365 days like this row.
    brief_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    input_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)
