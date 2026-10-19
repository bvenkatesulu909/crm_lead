"""Audit trail for sensitive changes.

``record_audit`` adds one row to ``audit_log`` inside the CURRENT transaction, so the audit
entry is saved if and only if the change itself is saved.

The table is append-only for the application: migration 0003 removes UPDATE and DELETE rights
from every role except the schema owner, so the API cannot rewrite history even if it has a bug.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, ForeignKeyConstraint, Identity, Index, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.auth.principal import Principal
from app.core.models import Base, TenantOwnedMixin, UUIDPrimaryKeyMixin
from app.core.request_context import get_request_id


class AuditLog(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "actor_user_id"], ["users.tenant_id", "users.id"], ondelete="RESTRICT"
        ),
        Index(
            "ix_audit_log_tenant_id_entity_type_entity_id_occurred_at",
            "tenant_id",
            "entity_type",
            "entity_id",
            "occurred_at",
        ),
    )

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    actor_subject: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(100))  # e.g. "lead.status_changed"
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    # {"field": {"old": ..., "new": ...}} or other structured details. Never secrets/tokens.
    changes: Mapped[dict[str, Any]] = mapped_column(JSONB)
    request_id: Mapped[str | None] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.clock_timestamp())
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))


def diff(old: dict[str, Any], new: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """{field: {"old": x, "new": y}} for every field whose value changed."""
    return {
        key: {"old": old.get(key), "new": value}
        for key, value in new.items()
        if old.get(key) != value
    }


def record_audit(
    session: Session,
    principal: Principal,
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    changes: dict[str, Any],
) -> None:
    if principal.tenant_id is None:
        raise ValueError("audited changes must belong to a tenant")
    session.add(
        AuditLog(
            tenant_id=principal.tenant_id,
            actor_user_id=principal.user_id,
            actor_subject=principal.subject,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            # JSON-safe copy: UUIDs, dates and decimals become strings.
            changes=_json_safe(changes),
            request_id=get_request_id(),
        )
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(v) for v in value]
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return str(value)
