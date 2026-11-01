"""Queries of the qualification procedures. All run inside the request's tenant context (RLS)."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.qualifier.models import QualificationProcedure


def lock_tenant(session: Session, tenant_id: uuid.UUID) -> None:
    """Make concurrent saves for one organisation take turns (released at commit)."""
    session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(str(tenant_id), 47))))


def get_active(session: Session, tenant_id: uuid.UUID) -> QualificationProcedure | None:
    return session.scalar(
        select(QualificationProcedure).where(
            QualificationProcedure.tenant_id == tenant_id, QualificationProcedure.active.is_(True)
        )
    )


def latest_version(session: Session, tenant_id: uuid.UUID) -> int:
    value = session.scalar(
        select(func.max(QualificationProcedure.version)).where(
            QualificationProcedure.tenant_id == tenant_id
        )
    )
    return int(value or 0)


def list_versions(
    session: Session, tenant_id: uuid.UUID, *, limit: int, offset: int
) -> tuple[list[QualificationProcedure], int]:
    total = session.scalar(
        select(func.count())
        .select_from(QualificationProcedure)
        .where(QualificationProcedure.tenant_id == tenant_id)
    )
    items = session.scalars(
        select(QualificationProcedure)
        .where(QualificationProcedure.tenant_id == tenant_id)
        .order_by(QualificationProcedure.version.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(items), int(total or 0)
