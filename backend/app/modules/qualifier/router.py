"""/api/v1/qualifier - the organisation's written lead-qualification procedure (QA1).

Thin layer: permissions, then the service; the write endpoints commit once. Tenant admins write,
sales managers and admins read, everyone else is refused.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.identity.api import require_any_permission
from app.modules.qualifier import service
from app.modules.qualifier.models import QualificationProcedure
from app.modules.qualifier.schemas import (
    ProcedureDeactivate,
    ProcedurePage,
    ProcedureRead,
    ProcedureSave,
)

router = APIRouter(prefix="/qualifier", tags=["qualifier"])
Db = Annotated[Session, Depends(get_db_session)]
Reader = Annotated[Principal, Depends(require_any_permission(Permission.QUALIFIER_READ))]
Manager = Annotated[Principal, Depends(require_any_permission(Permission.QUALIFIER_MANAGE))]


def _read(procedure: QualificationProcedure) -> ProcedureRead:
    return ProcedureRead(
        id=procedure.id,
        version=procedure.version,
        name=procedure.name,
        steps=list(procedure.steps),
        cleaned=[str(code) for code in procedure.cleaned],
        active=procedure.active,
        retired_at=procedure.retired_at,
        created_by_user_id=procedure.created_by_user_id,
        created_at=procedure.created_at,
    )


@router.get(
    "/procedure",
    summary="The active qualification procedure of your organisation",
    responses=problem_responses(401, 403, 404),
)
def get_procedure(principal: Reader, session: Db) -> ProcedureRead:
    return _read(service.get_active(session, principal))


@router.get(
    "/procedure/versions",
    summary="Every saved version of the procedure, newest first",
    responses=problem_responses(401, 403),
)
def list_versions(
    principal: Reader,
    session: Db,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProcedurePage:
    items, total = service.list_versions(session, principal, limit=limit, offset=offset)
    return ProcedurePage(items=[_read(i) for i in items], total=total, limit=limit, offset=offset)


@router.put(
    "/procedure",
    status_code=201,
    summary="Save the procedure as a new version (the previous one is kept in the history)",
    description="Links, addresses, markup and hidden characters are removed from the steps; a "
    "step that reads like an instruction to an AI is refused. Send `replaces_version` (the "
    "active version you edited) so two people cannot overwrite each other.",
    responses=problem_responses(401, 403, 409, 422),
)
def save_procedure(data: ProcedureSave, principal: Manager, session: Db) -> ProcedureRead:
    procedure = service.save_procedure(
        session,
        principal,
        name=data.name,
        steps=data.steps,
        replaces_version=data.replaces_version,
    )
    session.commit()
    return _read(procedure)


@router.post(
    "/procedure/deactivate",
    summary="Switch the procedure off; the Qualifier then does nothing until one is saved",
    responses=problem_responses(401, 403, 404, 409, 422),
)
def deactivate_procedure(
    data: ProcedureDeactivate, principal: Manager, session: Db
) -> ProcedureRead:
    procedure = service.deactivate(session, principal, version=data.version)
    session.commit()
    return _read(procedure)
