"""Custom agents (ADR 0034, AB1): a definition per agent and one insert-only row per version.

The agent row only names the agent and points at its newest version. Everything that decides what
the agent does lives in the version rows, which can never change (the database refuses an UPDATE
and an early DELETE), so every run can name the exact text it used.
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
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import (
    Base,
    TenantOwnedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    VersionedMixin,
)
from app.modules.custom_agents import rules


def _literal_array(values: tuple[str, ...]) -> str:
    return "ARRAY[" + ", ".join(f"'{value}'" for value in values) + "]::text[]"


class CustomAgent(UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "custom_agents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "agent_key"),
        ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("agent_key ~ '^custom_[a-z]{12}$'", name="key_format"),
        CheckConstraint(f"char_length(name) BETWEEN 1 AND {rules.NAME_MAX}", name="name_length"),
        CheckConstraint("current_version >= 1", name="version_positive"),
    )

    # The key the agent has in the agent registry (switch, budget, usage). Never a built-in name.
    agent_key: Mapped[str] = mapped_column(String(20), default=rules.new_agent_key)
    name: Mapped[str] = mapped_column(String(rules.NAME_MAX))
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    archived_at: Mapped[datetime | None] = mapped_column(default=None)


class CustomAgentVersion(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    __tablename__ = "custom_agent_versions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "custom_agent_id", "version_no"),
        ForeignKeyConstraint(
            ["tenant_id", "custom_agent_id"],
            ["custom_agents.tenant_id", "custom_agents.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("version_no >= 1", name="version_positive"),
        CheckConstraint(
            f"char_length(purpose) BETWEEN 1 AND {rules.PURPOSE_MAX}", name="purpose_length"
        ),
        CheckConstraint(
            f"char_length(instruction) BETWEEN 1 AND {rules.INSTRUCTION_MAX}",
            name="instruction_length",
        ),
        CheckConstraint(
            f"cardinality(read_sets) BETWEEN 1 AND {rules.MAX_READ_SETS} "
            f"AND read_sets <@ {_literal_array(tuple(rules.READ_SETS))}",
            name="read_sets_allowed",
        ),
        CheckConstraint(
            f"cardinality(suggestion_kinds) BETWEEN 1 AND {rules.MAX_SUGGESTION_KINDS} "
            f"AND suggestion_kinds <@ {_literal_array(rules.SUGGESTION_KINDS)}",
            name="suggestion_kinds_allowed",
        ),
        CheckConstraint("jsonb_typeof(cleaned) = 'array'", name="cleaned_is_list"),
        Index("ix_custom_agent_versions_tenant_id_custom_agent_id", "tenant_id", "custom_agent_id"),
    )

    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
    custom_agent_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    version_no: Mapped[int] = mapped_column(Integer)
    purpose: Mapped[str] = mapped_column(String(rules.PURPOSE_MAX))
    instruction: Mapped[str] = mapped_column(Text)
    read_sets: Mapped[list[str]] = mapped_column(ARRAY(Text))
    suggestion_kinds: Mapped[list[str]] = mapped_column(ARRAY(Text))
    # Codes of what was cleaned out of the typed text (never the text itself); a list of strings.
    cleaned: Mapped[Any] = mapped_column(JSONB)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


RUN_MODES = ("run", "trial")
RUN_OUTCOMES = ("proposed", "no_proposal", "blocked", "shown")


class CustomAgentRun(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    """One run, or one dry run ("trial"), of a custom agent on one record: which version it used,
    who asked and what came of it. Insert-only. Ids and codes only - never what the model wrote."""

    __tablename__ = "custom_agent_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "custom_agent_id", "version_no"],
            [
                "custom_agent_versions.tenant_id",
                "custom_agent_versions.custom_agent_id",
                "custom_agent_versions.version_no",
            ],
            name="fk_custom_agent_runs_agent_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "proposal_id"],
            ["agent_actions.tenant_id", "agent_actions.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("mode IN ('run', 'trial')", name="mode_allowed"),
        CheckConstraint(
            "outcome IN ('proposed', 'no_proposal', 'blocked', 'shown')", name="outcome_allowed"
        ),
        CheckConstraint("record_type IN ('lead', 'account', 'deal')", name="record_type_allowed"),
        CheckConstraint("action IN ('none', 'set_status', 'create_task')", name="action_allowed"),
        # A dry run never proposes; a proposal exists exactly when the outcome says so.
        CheckConstraint(
            "((mode = 'trial') = (outcome = 'shown')) AND ((outcome = 'proposed') = "
            "(proposal_id IS NOT NULL))",
            name="mode_outcome_proposal_consistent",
        ),
        Index("ix_custom_agent_runs_tenant_id_custom_agent_id", "tenant_id", "custom_agent_id"),
        Index("ix_custom_agent_runs_tenant_id_record_id", "tenant_id", "record_id"),
    )

    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
    custom_agent_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    version_no: Mapped[int] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(5))
    record_type: Mapped[str] = mapped_column(String(10))
    record_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(String(12))
    outcome: Mapped[str] = mapped_column(String(12))
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
