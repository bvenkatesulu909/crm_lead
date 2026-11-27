"""Saved filters (ADR 0042, BR-pre): a named set of an Accounts list's filter parameters."""

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
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
from app.modules.saved_filters import rules


class SavedFilter(UUIDPrimaryKeyMixin, TenantOwnedMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "saved_filters"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "owner_user_id"], ["users.tenant_id", "users.id"], ondelete="RESTRICT"
        ),
        CheckConstraint("record_type IN ('account')", name="record_type_allowed"),
        CheckConstraint(f"char_length(name) BETWEEN 1 AND {rules.NAME_MAX}", name="name_length"),
        CheckConstraint("jsonb_typeof(params) = 'object'", name="params_is_object"),
        # A person's own names are unique ignoring capitals; shared names are unique too.
        Index(
            "uq_saved_filters_owner_name",
            "tenant_id",
            "owner_user_id",
            "record_type",
            func.lower(text("name")),
            unique=True,
        ),
        Index(
            "uq_saved_filters_shared_name",
            "tenant_id",
            "record_type",
            func.lower(text("name")),
            unique=True,
            postgresql_where=text("shared"),
        ),
    )

    record_type: Mapped[str] = mapped_column(String(20), default="account")
    name: Mapped[str] = mapped_column(String(rules.NAME_MAX))
    params: Mapped[dict[str, str]] = mapped_column(JSONB)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    shared: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
