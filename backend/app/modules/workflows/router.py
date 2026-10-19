"""Workflow rule endpoints at /api/v1/workflows (tenant admins only)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.identity.api import require_any_permission
from app.modules.workflows import service
from app.modules.workflows.schemas import Catalogue, RuleCreate, RuleRead, RuleUpdate, RunRead

router = APIRouter(prefix="/workflows", tags=["workflows"], responses=problem_responses(401, 403))
Admin = Annotated[Principal, Depends(require_any_permission(Permission.WORKFLOW_MANAGE))]
Db = Annotated[Session, Depends(get_db_session)]


@router.get("/catalogue", summary="Triggers, fields, operators and actions rules can use")
def catalogue(principal: Admin) -> Catalogue:
    return service.get_catalogue()


@router.get("/rules", summary="All rules of your organisation")
def list_rules(principal: Admin, session: Db) -> list[RuleRead]:
    return service.list_rules(session, principal)


@router.post(
    "/rules",
    status_code=status.HTTP_201_CREATED,
    summary="Create a rule",
    responses=problem_responses(422),
)
def create_rule(data: RuleCreate, principal: Admin, session: Db) -> RuleRead:
    rule = service.create_rule(session, principal, data)
    session.commit()
    return rule


@router.get("/rules/{rule_id}", summary="One rule", responses=problem_responses(404))
def get_rule(rule_id: uuid.UUID, principal: Admin, session: Db) -> RuleRead:
    return service.get_rule(session, principal, rule_id)


@router.put("/rules/{rule_id}", summary="Change a rule", responses=problem_responses(404, 409, 422))
def update_rule(rule_id: uuid.UUID, data: RuleUpdate, principal: Admin, session: Db) -> RuleRead:
    rule = service.update_rule(session, principal, rule_id, data)
    session.commit()
    return rule


@router.delete(
    "/rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a rule (and its run log)",
    responses=problem_responses(404),
)
def delete_rule(rule_id: uuid.UUID, principal: Admin, session: Db) -> Response:
    service.delete_rule(session, principal, rule_id)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/runs", summary="Run log: what rules did, newest first")
def list_runs(
    principal: Admin,
    session: Db,
    rule_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[RunRead]:
    return service.list_runs(session, principal, rule_id=rule_id, limit=limit)
