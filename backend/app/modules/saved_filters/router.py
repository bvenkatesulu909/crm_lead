"""/api/v1/saved-filters - named filters of the Accounts list (ADR 0042, BR-pre).

Thin layer: permissions, then the service; write endpoints commit once. A saved filter is only
parameters: applying it is the same as typing them on the list, so the list's read rules decide
what comes back.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.identity.api import require_any_permission
from app.modules.saved_filters import service
from app.modules.saved_filters.models import SavedFilter
from app.modules.saved_filters.schemas import (
    SavedFilterCreate,
    SavedFilterPage,
    SavedFilterRead,
    SavedFilterUpdate,
)

router = APIRouter(prefix="/saved-filters", tags=["saved-filters"])
Db = Annotated[Session, Depends(get_db_session)]
Reader = Annotated[
    Principal,
    Depends(require_any_permission(Permission.ACCOUNT_READ_ALL, Permission.ACCOUNT_READ_OWN)),
]


def _read(item: SavedFilter, principal: Principal) -> SavedFilterRead:
    return SavedFilterRead(
        id=item.id,
        record_type="account",
        name=item.name,
        params=item.params,
        shared=item.shared,
        owner_user_id=item.owner_user_id,
        mine=item.owner_user_id == principal.user_id,
        version=item.version,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get("", summary="Your saved account filters and the shared ones")
def list_filters(principal: Reader, session: Db) -> SavedFilterPage:
    return SavedFilterPage(
        items=[_read(f, principal) for f in service.list_filters(session, principal)]
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Save the current account filter under a name",
    responses=problem_responses(403, 409, 422),
)
def create_filter(body: SavedFilterCreate, principal: Reader, session: Db) -> SavedFilterRead:
    item = service.create_filter(
        session, principal, name=body.name, params=body.params, shared=body.shared
    )
    session.commit()
    return _read(item, principal)


@router.get("/{filter_id}", summary="One saved filter", responses=problem_responses(404))
def get_filter(filter_id: uuid.UUID, principal: Reader, session: Db) -> SavedFilterRead:
    return _read(service.get_filter(session, principal, filter_id), principal)


@router.patch(
    "/{filter_id}",
    summary="Rename, change or share a saved filter",
    responses=problem_responses(403, 404, 409, 422),
)
def update_filter(
    filter_id: uuid.UUID, body: SavedFilterUpdate, principal: Reader, session: Db
) -> SavedFilterRead:
    item = service.update_filter(
        session,
        principal,
        filter_id,
        version=body.version,
        name=body.name,
        params=body.params,
        shared=body.shared,
    )
    session.commit()
    return _read(item, principal)


@router.delete(
    "/{filter_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a saved filter",
    responses=problem_responses(403, 404),
)
def delete_filter(filter_id: uuid.UUID, principal: Reader, session: Db) -> Response:
    service.delete_filter(session, principal, filter_id)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
