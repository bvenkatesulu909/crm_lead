"""Public interface of the units module (ADR 0040); the reservation steps read units here."""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.units.models import PropertyProject, PropertyUnit

__all__ = ["UnitInfo", "unit_info"]


@dataclass(frozen=True)
class UnitInfo:
    id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    unit_code: str
    unit_type: str
    price: Decimal
    status: str


def unit_info(session: Session, tenant_id: uuid.UUID, unit_id: uuid.UUID) -> UnitInfo | None:
    """One unit of this organisation (None when missing or someone else's)."""
    row = session.execute(
        select(PropertyUnit, PropertyProject.name)
        .join(
            PropertyProject,
            (PropertyProject.tenant_id == PropertyUnit.tenant_id)
            & (PropertyProject.id == PropertyUnit.project_id),
        )
        .where(PropertyUnit.tenant_id == tenant_id, PropertyUnit.id == unit_id)
    ).one_or_none()
    if row is None:
        return None
    unit, project_name = row
    return UnitInfo(
        unit.id,
        unit.project_id,
        project_name,
        unit.unit_code,
        unit.unit_type,
        unit.price,
        unit.status,
    )
