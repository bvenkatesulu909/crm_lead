"""Queries of the photo enhancer. Every one is scoped by tenant."""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.photo_enhancer.models import PhotoEnhancement


def add(session: Session, row: PhotoEnhancement) -> PhotoEnhancement:
    session.add(row)
    session.flush()
    return row


def get(
    session: Session, tenant_id: uuid.UUID, enhancement_id: uuid.UUID
) -> PhotoEnhancement | None:
    return session.scalars(
        select(PhotoEnhancement).where(
            PhotoEnhancement.tenant_id == tenant_id, PhotoEnhancement.id == enhancement_id
        )
    ).one_or_none()


def lock(
    session: Session, tenant_id: uuid.UUID, enhancement_id: uuid.UUID
) -> PhotoEnhancement | None:
    return session.scalars(
        select(PhotoEnhancement)
        .where(PhotoEnhancement.tenant_id == tenant_id, PhotoEnhancement.id == enhancement_id)
        .with_for_update()
    ).one_or_none()


def list_of_original(
    session: Session, tenant_id: uuid.UUID, original_document_id: uuid.UUID
) -> list[PhotoEnhancement]:
    return list(
        session.scalars(
            select(PhotoEnhancement)
            .where(
                PhotoEnhancement.tenant_id == tenant_id,
                PhotoEnhancement.original_document_id == original_document_id,
            )
            .order_by(PhotoEnhancement.created_at.desc(), PhotoEnhancement.id)
        ).all()
    )


def count_of_original(
    session: Session, tenant_id: uuid.UUID, original_document_id: uuid.UUID
) -> int:
    """Requests that still count against the per-photo limit: waiting or made (not failed)."""
    return int(
        session.scalar(
            select(func.count())
            .select_from(PhotoEnhancement)
            .where(
                PhotoEnhancement.tenant_id == tenant_id,
                PhotoEnhancement.original_document_id == original_document_id,
                PhotoEnhancement.status != "failed",
            )
        )
        or 0
    )


def count_started(
    session: Session, tenant_id: uuid.UUID, since: datetime, *, user_id: uuid.UUID | None = None
) -> int:
    statement = (
        select(func.count())
        .select_from(PhotoEnhancement)
        .where(PhotoEnhancement.tenant_id == tenant_id, PhotoEnhancement.created_at >= since)
    )
    if user_id is not None:
        statement = statement.where(PhotoEnhancement.requested_by_user_id == user_id)
    return int(session.scalar(statement) or 0)
