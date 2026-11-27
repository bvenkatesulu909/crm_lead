"""Queries of saved filters. Every query names the organisation (row-level security is the second
wall, ADR 0009) and the visibility rule is applied in SQL: own filters plus shared ones."""

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.modules.saved_filters.models import SavedFilter


def list_visible(
    session: Session, tenant_id: uuid.UUID, user_id: uuid.UUID, record_type: str
) -> list[SavedFilter]:
    query = (
        select(SavedFilter)
        .where(
            SavedFilter.tenant_id == tenant_id,
            SavedFilter.record_type == record_type,
            or_(SavedFilter.owner_user_id == user_id, SavedFilter.shared.is_(True)),
        )
        .order_by(func.lower(SavedFilter.name), SavedFilter.id)
    )
    return list(session.scalars(query))


def get_visible(
    session: Session, tenant_id: uuid.UUID, user_id: uuid.UUID, filter_id: uuid.UUID
) -> SavedFilter | None:
    return session.scalars(
        select(SavedFilter).where(
            SavedFilter.tenant_id == tenant_id,
            SavedFilter.id == filter_id,
            or_(SavedFilter.owner_user_id == user_id, SavedFilter.shared.is_(True)),
        )
    ).first()


def count_own(session: Session, tenant_id: uuid.UUID, user_id: uuid.UUID) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(SavedFilter)
            .where(SavedFilter.tenant_id == tenant_id, SavedFilter.owner_user_id == user_id)
        )
        or 0
    )


def count_shared(session: Session, tenant_id: uuid.UUID) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(SavedFilter)
            .where(SavedFilter.tenant_id == tenant_id, SavedFilter.shared.is_(True))
        )
        or 0
    )


def name_taken(
    session: Session,
    tenant_id: uuid.UUID,
    owner_id: uuid.UUID,
    name: str,
    *,
    shared: bool,
    except_id: uuid.UUID | None = None,
) -> bool:
    """Own names are unique per person; a shared name is unique across the organisation."""
    query = (
        select(func.count())
        .select_from(SavedFilter)
        .where(SavedFilter.tenant_id == tenant_id, func.lower(SavedFilter.name) == name.lower())
    )
    if shared:
        query = query.where(SavedFilter.shared.is_(True))
    else:
        query = query.where(SavedFilter.owner_user_id == owner_id)
    if except_id is not None:
        query = query.where(SavedFilter.id != except_id)
    return bool(session.scalar(query))
