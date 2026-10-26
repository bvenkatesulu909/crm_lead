"""Per-organisation settings and monthly usage of the CRM's AI agents (ADR 0016).

``agent_settings`` holds only an organisation's OVERRIDES of the defaults (a missing row means:
on, default budget, all tools). ``agent_usage`` is a running total per month - counts only, never
prompts or answers - kept by one atomic upsert so concurrent calls cannot lose tokens.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import (
    Base,
    TenantOwnedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    VersionedMixin,
)
from app.modules.agents.catalogue import KEY_PATTERN

MAX_TOKENS = 10_000_000_000  # one organisation, one agent, one month


class AgentSetting(UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "agent_settings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "agent_key"),
        ForeignKeyConstraint(
            ["tenant_id", "updated_by_user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(f"agent_key ~ '{KEY_PATTERN}'", name="agent_key_shape"),
        CheckConstraint(
            f"monthly_token_budget IS NULL OR monthly_token_budget BETWEEN 1 AND {MAX_TOKENS}",
            name="budget_range",
        ),
    )

    agent_key: Mapped[str] = mapped_column(String(40))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    # NULL = the default budget from the settings; a number = this organisation's own cap.
    monthly_token_budget: Mapped[int | None] = mapped_column(BigInteger)
    # NULL = every tool the catalogue lists; a list (maybe empty) = only these.
    allowed_tools: Mapped[list[str] | None] = mapped_column(ARRAY(String(60)))
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class AgentUsage(UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, Base):
    __tablename__ = "agent_usage"
    __table_args__ = (
        UniqueConstraint("tenant_id", "agent_key", "month"),
        CheckConstraint(f"agent_key ~ '{KEY_PATTERN}'", name="agent_key_shape"),
        CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND calls >= 0", name="counts_not_negative"
        ),
        # The first day of a UTC month: one row per month, never a free-form date.
        CheckConstraint("date_part('day', month) = 1", name="month_is_first_day"),
        Index("ix_agent_usage_tenant_id_month", "tenant_id", "month"),
    )

    agent_key: Mapped[str] = mapped_column(String(40))
    month: Mapped[date] = mapped_column(Date)
    input_tokens: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    calls: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    # Set once, when the month's total first passes the warning share of the budget.
    warned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
