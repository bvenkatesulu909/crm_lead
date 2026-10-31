"""The organisation's written lead-qualification procedure (BP-03, docs/qualifier.md).

One row per VERSION. A new text is a new row; the previous active version is retired (its
``active`` flag turns false, nothing else ever changes - the database enforces it). At most one
version per organisation is active.
"""

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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantOwnedMixin, UUIDPrimaryKeyMixin

MAX_STEPS = 20
MAX_STEP_CHARS = 300
MIN_STEP_CHARS = 3
MAX_TOTAL_CHARS = 4000
MAX_NAME_CHARS = 100


class QualificationProcedure(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    __tablename__ = "qualification_procedures"
    __table_args__ = (
        UniqueConstraint("tenant_id", "version"),
        ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(f"char_length(name) BETWEEN 1 AND {MAX_NAME_CHARS}", name="name_length"),
        CheckConstraint(
            "jsonb_typeof(steps) = 'array' "
            f"AND jsonb_array_length(steps) BETWEEN 1 AND {MAX_STEPS}",
            name="steps_count",
        ),
        CheckConstraint("jsonb_typeof(cleaned) = 'array'", name="cleaned_is_list"),
        CheckConstraint("(active) = (retired_at IS NULL)", name="retired_means_inactive"),
        # At most one active procedure per organisation.
        Index(
            "uq_qualification_procedures_one_active",
            "tenant_id",
            unique=True,
            postgresql_where=text("active"),
        ),
    )

    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(MAX_NAME_CHARS))
    # The cleaned steps, in order; a list of strings.
    steps: Mapped[list[str]] = mapped_column(JSONB)
    # Kinds of text taken out while cleaning (codes only, never the text itself).
    cleaned: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    retired_at: Mapped[datetime | None] = mapped_column(default=None)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
