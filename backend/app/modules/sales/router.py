"""Opportunity (pipeline) endpoints, mounted at /api/v1/opportunities.

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
from app.modules.sales import service
from app.modules.sales.repository import OpportunityFilters
from app.modules.sales.schemas import (
    Board,
    MarkLost,
    MarkWon,
    OpportunityCreate,
    OpportunityPage,
    OpportunityRead,
    OpportunityUpdate,
    Reopen,
    Stage,
    StageChangeRead,
    StageMove,
)

router = APIRouter(
    prefix="/opportunities", tags=["opportunities"], responses=problem_responses(401, 403)
)
Reader = Annotated[
    Principal,
    Depends(
        require_any_permission(Permission.OPPORTUNITY_READ_ALL, Permission.OPPORTUNITY_READ_OWN)
    ),
]
Writer = Annotated[
    Principal,
    Depends(
        require_any_permission(Permission.OPPORTUNITY_WRITE_ALL, Permission.OPPORTUNITY_WRITE_OWN)
    ),
]
Db = Annotated[Session, Depends(get_db_session)]
Q = Annotated[str | None, Query(min_length=1, max_length=100)]


def _read(o: object) -> OpportunityRead:
    return OpportunityRead.model_validate(o)


@router.get("", summary="List the opportunities you may see (newest first)")
def list_opportunities(
    principal: Reader,
    session: Db,
    q: Q = None,
    account_id: uuid.UUID | None = None,
    owner_id: uuid.UUID | None = None,
    stage: Annotated[list[Stage] | None, Query()] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=100_000),
) -> OpportunityPage:
    filters = OpportunityFilters(
        q=q.strip() if q else None,
        account_id=account_id,
        owner_id=owner_id,
        stages=tuple(stage or ()),
        limit=limit,
        offset=offset,
    )
    items, total = service.list_opportunities(session, principal, filters)
    return OpportunityPage(items=[_read(o) for o in items], total=total, limit=limit, offset=offset)


@router.get(
    "/board",
    summary="Pipeline board: one column per open stage, plus recently won and lost",
    description="Each column has its count, value and weighted value per currency (all "
    "matching deals) and up to `limit` cards, closing soonest first. Won/lost columns cover "
    "deals closed in the last `closed_days` days.",
)
def get_board(
    principal: Reader,
    session: Db,
    q: Q = None,
    account_id: uuid.UUID | None = None,
    owner_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    closed_days: int = Query(default=30, ge=1, le=366),
) -> Board:
    filters = OpportunityFilters(
        q=q.strip() if q else None, account_id=account_id, owner_id=owner_id
    )
    return service.board(session, principal, filters, limit=limit, closed_days=closed_days)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create an opportunity",
    responses=problem_responses(404, 422),
)
def create_opportunity(
    data: OpportunityCreate, principal: Writer, session: Db, response: Response
) -> OpportunityRead:
    o = service.create_opportunity(session, principal, data)
    session.commit()
    response.headers["Location"] = f"/api/v1/opportunities/{o.id}"
    return _read(o)


@router.get("/{opportunity_id}", summary="Get one opportunity", responses=problem_responses(404))
def get_opportunity(opportunity_id: uuid.UUID, principal: Reader, session: Db) -> OpportunityRead:
    return _read(service.get_opportunity(session, principal, opportunity_id))


@router.patch(
    "/{opportunity_id}",
    summary="Change an open opportunity (value, close date, contact, owner, next step...)",
    responses=problem_responses(404, 409, 422),
)
def update_opportunity(
    opportunity_id: uuid.UUID, data: OpportunityUpdate, principal: Writer, session: Db
) -> OpportunityRead:
    o = service.update_opportunity(session, principal, opportunity_id, data)
    session.commit()
    return _read(o)


@router.post(
    "/{opportunity_id}/stage",
    summary="Move an open opportunity to another open stage (Kanban)",
    responses=problem_responses(404, 409, 422),
)
def move_stage(
    opportunity_id: uuid.UUID, data: StageMove, principal: Writer, session: Db
) -> OpportunityRead:
    o = service.move_stage(
        session, principal, opportunity_id, version=data.version, stage=data.stage, note=data.note
    )
    session.commit()
    return _read(o)


@router.post(
    "/{opportunity_id}/won",
    summary="Mark as won (needs a deal value)",
    responses=problem_responses(404, 409, 422),
)
def mark_won(
    opportunity_id: uuid.UUID, data: MarkWon, principal: Writer, session: Db
) -> OpportunityRead:
    o = service.mark_won(session, principal, opportunity_id, version=data.version, note=data.note)
    session.commit()
    return _read(o)


@router.post(
    "/{opportunity_id}/lost",
    summary="Mark as lost (needs a reason)",
    responses=problem_responses(404, 409, 422),
)
def mark_lost(
    opportunity_id: uuid.UUID, data: MarkLost, principal: Writer, session: Db
) -> OpportunityRead:
    o = service.mark_lost(
        session, principal, opportunity_id, version=data.version, reason=data.reason
    )
    session.commit()
    return _read(o)


@router.post(
    "/{opportunity_id}/reopen",
    summary="Reopen a won or lost deal (managers and administrators)",
    responses=problem_responses(404, 409, 422),
)
def reopen(
    opportunity_id: uuid.UUID, data: Reopen, principal: Writer, session: Db
) -> OpportunityRead:
    o = service.reopen(
        session, principal, opportunity_id, version=data.version, stage=data.stage, note=data.note
    )
    session.commit()
    return _read(o)


@router.get(
    "/{opportunity_id}/stages",
    summary="Stage history (newest first)",
    responses=problem_responses(404),
)
def stage_history(
    opportunity_id: uuid.UUID, principal: Reader, session: Db
) -> list[StageChangeRead]:
    return service.stage_history(session, principal, opportunity_id)
