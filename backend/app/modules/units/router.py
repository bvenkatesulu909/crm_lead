"""Endpoints: /api/v1/projects and /api/v1/units (ADR 0040, RP1).

Thin layer: check the caller's coarse permission (RBAC), call the service, commit once.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.identity.api import require_any_permission
from app.modules.units import service
from app.modules.units.schemas import (
    ProjectCreate,
    ProjectPage,
    ProjectRead,
    ProjectUpdate,
    UnitCreate,
    UnitPage,
    UnitRead,
    UnitStatus,
    UnitType,
    UnitUpdate,
)

router = APIRouter(tags=["units"], responses=problem_responses(401, 403))
Reader = Annotated[Principal, Depends(require_any_permission(Permission.UNIT_READ))]
Manager = Annotated[Principal, Depends(require_any_permission(Permission.UNIT_MANAGE))]
Db = Annotated[Session, Depends(get_db_session)]


@router.get("/projects", summary="List and search projects")
def list_projects(
    principal: Reader,
    session: Db,
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    active: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=100_000),
) -> ProjectPage:
    items, total = service.list_projects(
        session, principal, q=q.strip() if q else None, active=active, limit=limit, offset=offset
    )
    return ProjectPage(
        items=[ProjectRead.model_validate(p) for p in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/projects",
    status_code=status.HTTP_201_CREATED,
    summary="Add a project (managers)",
    responses=problem_responses(409, 422),
)
def create_project(
    data: ProjectCreate, principal: Manager, session: Db, response: Response
) -> ProjectRead:
    project = service.create_project(session, principal, data)
    session.commit()
    response.headers["Location"] = f"/api/v1/projects/{project.id}"
    return ProjectRead.model_validate(project)


@router.get("/projects/{project_id}", summary="Get one project", responses=problem_responses(404))
def get_project(project_id: uuid.UUID, principal: Reader, session: Db) -> ProjectRead:
    return ProjectRead.model_validate(service.get_project(session, principal, project_id))


@router.patch(
    "/projects/{project_id}",
    summary="Change or deactivate a project (managers)",
    responses=problem_responses(404, 409, 422),
)
def update_project(
    project_id: uuid.UUID, data: ProjectUpdate, principal: Manager, session: Db
) -> ProjectRead:
    project = service.update_project(session, principal, project_id, data)
    session.commit()
    return ProjectRead.model_validate(project)


@router.get("/units", summary="List and search units")
def list_units(
    principal: Reader,
    session: Db,
    project_id: uuid.UUID | None = None,
    unit_status: Annotated[UnitStatus | None, Query(alias="status")] = None,
    unit_type: UnitType | None = None,
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=100_000),
) -> UnitPage:
    items, total = service.list_units(
        session,
        principal,
        project_id=project_id,
        status=unit_status,
        unit_type=unit_type,
        q=q.strip() if q else None,
        limit=limit,
        offset=offset,
    )
    return UnitPage(
        items=[UnitRead.model_validate(u) for u in items], total=total, limit=limit, offset=offset
    )


@router.post(
    "/units",
    status_code=status.HTTP_201_CREATED,
    summary="Add a unit to a project (managers)",
    responses=problem_responses(404, 409, 422),
)
def create_unit(data: UnitCreate, principal: Manager, session: Db, response: Response) -> UnitRead:
    unit = service.create_unit(session, principal, data)
    session.commit()
    response.headers["Location"] = f"/api/v1/units/{unit.id}"
    return UnitRead.model_validate(unit)


@router.get("/units/{unit_id}", summary="Get one unit", responses=problem_responses(404))
def get_unit(unit_id: uuid.UUID, principal: Reader, session: Db) -> UnitRead:
    return UnitRead.model_validate(service.get_unit(session, principal, unit_id))


@router.patch(
    "/units/{unit_id}",
    summary="Change, block or release a unit (managers; audited)",
    responses=problem_responses(404, 409, 422),
)
def update_unit(unit_id: uuid.UUID, data: UnitUpdate, principal: Manager, session: Db) -> UnitRead:
    unit = service.update_unit(session, principal, unit_id, data)
    session.commit()
    return UnitRead.model_validate(unit)
