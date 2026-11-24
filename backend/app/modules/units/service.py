"""Projects and units (ADR 0040, RP1). Functions here never commit: the router commits once.

- Everyone in sales reads units (``unit:read``); managers and administrators (``unit:manage``)
  create and change them. Support and customers have no access.
- The tenant comes from the verified token only. A project or unit id from the client is looked up
  through the tenant filter (and row-level security): not found -> 404.
- A person can only set the status ``available`` or ``blocked``, and only while the unit is one of
  those two. ``reserved`` and ``sold`` belong to the reservation steps and cannot be set or undone
  here, so a held unit cannot be released by editing it.
- Prices and areas are ``Decimal``. A price change is audited (old and new, as text).
- Nothing is deleted: a project is deactivated, a unit is blocked.
"""

import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.audit import diff, record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.core.search import escape_like
from app.modules.units.models import MANUAL_STATUSES, PropertyProject, PropertyUnit
from app.modules.units.schemas import ProjectCreate, ProjectUpdate, UnitCreate, UnitUpdate

_PROJECT_FIELDS = ("name", "location", "rera_number", "is_active")
_UNIT_FIELDS = ("unit_code", "unit_type", "price", "area_sqft", "status")


class ProjectNotFoundError(NotFoundError):
    code = "project_not_found"

    def __init__(self) -> None:
        super().__init__("Project not found.")


class UnitNotFoundError(NotFoundError):
    code = "unit_not_found"

    def __init__(self) -> None:
        super().__init__("Unit not found.")


class DuplicateError(ConflictError):
    code = "already_exists"


class VersionConflictError(ConflictError):
    code = "version_conflict"


class ProjectInactiveError(ConflictError):
    code = "project_inactive"


class UnitStatusLockedError(ConflictError):
    code = "unit_status_locked"


def _tenant(principal: Principal, *, manage: bool = False) -> uuid.UUID:
    if principal.tenant_id is None or principal.user_type != "staff":
        raise ForbiddenError("Only staff of an organisation can use projects and units.")
    needed = Permission.UNIT_MANAGE if manage else Permission.UNIT_READ
    if not principal.has_permission(needed):
        raise ForbiddenError("Your role may not do this with projects and units.")
    return principal.tenant_id


def _flush(session: Session, what: str) -> None:
    try:
        session.flush()
    except StaleDataError as exc:
        raise VersionConflictError(f"The {what} was changed by someone else. Reload it.") from exc
    except IntegrityError as exc:
        raise DuplicateError(f"A {what} with this name or code already exists.") from exc


def _check_version(current: int, sent: int, what: str) -> None:
    if current != sent:
        raise VersionConflictError(
            f"The {what} was changed by someone else (now version {current}). Reload it."
        )


def _audit_value(value: object) -> object:
    """Audit entries are JSON: money and areas are written as text, exactly."""
    return str(value) if isinstance(value, Decimal) else value


def _changes(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        key: {"old": _audit_value(change["old"]), "new": _audit_value(change["new"])}
        for key, change in diff(before, after).items()
    }


# --- projects ----------------------------------------------------------------------------


def list_projects(
    session: Session,
    principal: Principal,
    *,
    q: str | None,
    active: bool | None,
    limit: int,
    offset: int,
) -> tuple[Sequence[PropertyProject], int]:
    tenant_id = _tenant(principal)
    statement = select(PropertyProject).where(PropertyProject.tenant_id == tenant_id)
    if q:
        pattern = f"%{escape_like(q)}%"
        statement = statement.where(
            or_(
                PropertyProject.name.ilike(pattern, escape="\\"),
                PropertyProject.location.ilike(pattern, escape="\\"),
            )
        )
    if active is not None:
        statement = statement.where(PropertyProject.is_active.is_(active))
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = session.scalars(
        statement.order_by(func.lower(PropertyProject.name), PropertyProject.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return rows, total


def get_project(session: Session, principal: Principal, project_id: uuid.UUID) -> PropertyProject:
    tenant_id = _tenant(principal)
    project = session.scalars(
        select(PropertyProject).where(
            PropertyProject.tenant_id == tenant_id, PropertyProject.id == project_id
        )
    ).one_or_none()
    if project is None:
        raise ProjectNotFoundError()
    return project


def _project_name_taken(
    session: Session, tenant_id: uuid.UUID, name: str, except_id: uuid.UUID | None
) -> bool:
    statement = select(PropertyProject.id).where(
        PropertyProject.tenant_id == tenant_id, func.lower(PropertyProject.name) == name.lower()
    )
    if except_id is not None:
        statement = statement.where(PropertyProject.id != except_id)
    return session.scalar(statement.limit(1)) is not None


def create_project(session: Session, principal: Principal, data: ProjectCreate) -> PropertyProject:
    tenant_id = _tenant(principal, manage=True)
    if _project_name_taken(session, tenant_id, data.name, None):
        raise DuplicateError("Another project already uses this name.")
    project = PropertyProject(tenant_id=tenant_id, **data.model_dump())
    session.add(project)
    _flush(session, "project")
    record_audit(
        session,
        principal,
        action="project.created",
        entity_type="property_project",
        entity_id=project.id,
        changes={"name": project.name},
    )
    _flush(session, "project")
    session.refresh(project)
    return project


def update_project(
    session: Session, principal: Principal, project_id: uuid.UUID, data: ProjectUpdate
) -> PropertyProject:
    _tenant(principal, manage=True)
    project = get_project(session, principal, project_id)
    _check_version(project.version, data.version, "project")
    if data.name and _project_name_taken(session, project.tenant_id, data.name, project.id):
        raise DuplicateError("Another project already uses this name.")
    before = {f: getattr(project, f) for f in _PROJECT_FIELDS}
    for field, value in data.changes().items():
        setattr(project, field, value)
    changed = _changes(before, {f: getattr(project, f) for f in _PROJECT_FIELDS})
    if changed:
        record_audit(
            session,
            principal,
            action="project.updated",
            entity_type="property_project",
            entity_id=project.id,
            changes=changed,
        )
    _flush(session, "project")
    session.refresh(project)
    return project


# --- units -------------------------------------------------------------------------------


def list_units(
    session: Session,
    principal: Principal,
    *,
    project_id: uuid.UUID | None,
    status: str | None,
    unit_type: str | None,
    q: str | None,
    limit: int,
    offset: int,
) -> tuple[Sequence[PropertyUnit], int]:
    tenant_id = _tenant(principal)
    statement = select(PropertyUnit).where(PropertyUnit.tenant_id == tenant_id)
    if project_id is not None:
        statement = statement.where(PropertyUnit.project_id == project_id)
    if status:
        statement = statement.where(PropertyUnit.status == status)
    if unit_type:
        statement = statement.where(PropertyUnit.unit_type == unit_type)
    if q:
        statement = statement.where(
            PropertyUnit.unit_code.ilike(f"%{escape_like(q)}%", escape="\\")
        )
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = session.scalars(
        statement.order_by(
            PropertyUnit.project_id, func.lower(PropertyUnit.unit_code), PropertyUnit.id
        )
        .limit(limit)
        .offset(offset)
    ).all()
    return rows, total


def get_unit(session: Session, principal: Principal, unit_id: uuid.UUID) -> PropertyUnit:
    tenant_id = _tenant(principal)
    unit = session.scalars(
        select(PropertyUnit).where(PropertyUnit.tenant_id == tenant_id, PropertyUnit.id == unit_id)
    ).one_or_none()
    if unit is None:
        raise UnitNotFoundError()
    return unit


def _code_taken(
    session: Session,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    code: str,
    except_id: uuid.UUID | None,
) -> bool:
    statement = select(PropertyUnit.id).where(
        PropertyUnit.tenant_id == tenant_id,
        PropertyUnit.project_id == project_id,
        func.lower(PropertyUnit.unit_code) == code.lower(),
    )
    if except_id is not None:
        statement = statement.where(PropertyUnit.id != except_id)
    return session.scalar(statement.limit(1)) is not None


def create_unit(session: Session, principal: Principal, data: UnitCreate) -> PropertyUnit:
    tenant_id = _tenant(principal, manage=True)
    project = get_project(session, principal, data.project_id)  # 404 for a foreign project
    if not project.is_active:
        raise ProjectInactiveError("This project is inactive; reactivate it to add units.")
    if _code_taken(session, tenant_id, project.id, data.unit_code, None):
        raise DuplicateError("Another unit in this project already uses this code.")
    unit = PropertyUnit(tenant_id=tenant_id, status="available", **data.model_dump())
    session.add(unit)
    _flush(session, "unit")
    record_audit(
        session,
        principal,
        action="unit.created",
        entity_type="property_unit",
        entity_id=unit.id,
        changes={
            "project_id": str(unit.project_id),
            "unit_code": unit.unit_code,
            "price": str(unit.price),
        },
    )
    _flush(session, "unit")
    session.refresh(unit)
    return unit


def update_unit(
    session: Session, principal: Principal, unit_id: uuid.UUID, data: UnitUpdate
) -> PropertyUnit:
    _tenant(principal, manage=True)
    # Lock the row: a reservation step may be changing its status at the same moment.
    unit = session.scalars(
        select(PropertyUnit)
        .where(PropertyUnit.tenant_id == principal.tenant_id, PropertyUnit.id == unit_id)
        .with_for_update()
    ).one_or_none()
    if unit is None:
        raise UnitNotFoundError()
    _check_version(unit.version, data.version, "unit")
    changes = data.changes()
    if unit.status not in MANUAL_STATUSES:
        # A held or sold unit is only changed by the reservation steps - not even its price.
        raise UnitStatusLockedError(
            f"This unit is {unit.status}; it can only be changed through its reservation."
        )
    if "unit_code" in changes and _code_taken(
        session, unit.tenant_id, unit.project_id, str(changes["unit_code"]), unit.id
    ):
        raise DuplicateError("Another unit in this project already uses this code.")
    before = {f: getattr(unit, f) for f in _UNIT_FIELDS}
    for field, value in changes.items():
        setattr(unit, field, value)
    changed = _changes(before, {f: getattr(unit, f) for f in _UNIT_FIELDS})
    if changed:
        record_audit(
            session,
            principal,
            action="unit.updated",
            entity_type="property_unit",
            entity_id=unit.id,
            changes=changed,
        )
    _flush(session, "unit")
    session.refresh(unit)
    return unit
