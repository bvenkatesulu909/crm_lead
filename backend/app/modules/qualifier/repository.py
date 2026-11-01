"""Queries of the qualification procedures. All run inside the request's tenant context (RLS)."""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.qualifier.models import LeadAssessment, QualificationProcedure


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


def count_assessments(
    session: Session,
    tenant_id: uuid.UUID,
    *,
    since: datetime,
    lead_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> int:
    """How many assessments of this organisation (optionally of one lead or by one person) were
    made since ``since``. Counts what was stored: a refused answer is not an assessment."""
    statement = (
        select(func.count())
        .select_from(LeadAssessment)
        .where(LeadAssessment.tenant_id == tenant_id, LeadAssessment.created_at >= since)
    )
    if lead_id is not None:
        statement = statement.where(LeadAssessment.lead_id == lead_id)
    if user_id is not None:
        statement = statement.where(LeadAssessment.requested_by_user_id == user_id)
    return int(session.scalar(statement) or 0)


def list_assessments(
    session: Session, tenant_id: uuid.UUID, lead_id: uuid.UUID, *, limit: int, offset: int
) -> tuple[list[LeadAssessment], int]:
    where = (LeadAssessment.tenant_id == tenant_id, LeadAssessment.lead_id == lead_id)
    total = session.scalar(select(func.count()).select_from(LeadAssessment).where(*where))
    items = session.scalars(
        select(LeadAssessment)
        .where(*where)
        .order_by(LeadAssessment.seq.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(items), int(total or 0)
