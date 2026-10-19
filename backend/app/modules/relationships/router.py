"""Ownership transfer and customer-health endpoints.

Thin layer: check the caller's coarse permission (RBAC), call the service, commit once.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.identity.api import require_any_permission
from app.modules.relationships import service
from app.modules.relationships.schemas import (
    HealthOverview,
    HealthRead,
    Transfer,
    TransferResult,
)

router = APIRouter(tags=["customer relationships"], responses=problem_responses(401, 403))
Reader = Annotated[
    Principal,
    Depends(require_any_permission(Permission.ACCOUNT_READ_ALL, Permission.ACCOUNT_READ_OWN)),
]
Manager = Annotated[Principal, Depends(require_any_permission(Permission.ACCOUNT_WRITE_ALL))]
Db = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/accounts/{account_id}/transfer",
    summary="Transfer a customer to another sales employee (managers and administrators)",
    description="Moves the account and, by default, its contacts, open deals and open tasks "
    "that belonged to the previous owner - all in one step, with a reason in the history.",
    responses=problem_responses(404, 409, 422),
)
def transfer(
    account_id: uuid.UUID, data: Transfer, principal: Manager, session: Db
) -> TransferResult:
    result = service.transfer(session, principal, account_id, data)
    session.commit()
    return result


@router.get(
    "/accounts/{account_id}/health",
    summary="Customer health: score, inactivity and the factors behind them",
    responses=problem_responses(404),
)
def account_health(account_id: uuid.UUID, principal: Reader, session: Db) -> HealthRead:
    return service.account_health(session, principal, account_id)


@router.get(
    "/customer-health",
    summary="Customers needing attention (least healthy first)",
    description="Assesses up to `limit` accounts you may see. Counts only; details are on "
    "each account's health.",
)
def overview(
    principal: Reader,
    session: Db,
    owner_id: uuid.UUID | None = None,
    limit: int = Query(default=200, ge=1, le=500),
) -> HealthOverview:
    return service.overview(session, principal, owner_id=owner_id, limit=limit)
