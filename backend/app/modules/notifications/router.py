"""Notification endpoints at /api/v1/notifications - always the signed-in person's own."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.identity.api import require_any_permission
from app.modules.notifications import service
from app.modules.notifications.schemas import NotificationPage, PreferenceRead, PreferencesUpdate

router = APIRouter(
    prefix="/notifications", tags=["notifications"], responses=problem_responses(401, 403)
)
Me = Annotated[Principal, Depends(require_any_permission(Permission.NOTIFICATION_READ))]
Db = Annotated[Session, Depends(get_db_session)]


@router.get("", summary="My notifications (newest first) and how many are unread")
def my_notifications(
    principal: Me,
    session: Db,
    unread_only: bool = False,
    limit: int = Query(default=30, ge=1, le=200),
) -> NotificationPage:
    return service.list_notifications(session, principal, unread_only=unread_only, limit=limit)


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT, summary="Mark all as read")
def read_all(principal: Me, session: Db) -> Response:
    service.mark_all_read(session, principal)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/preferences", summary="Which notifications also come by e-mail")
def my_preferences(principal: Me, session: Db) -> list[PreferenceRead]:
    return service.preferences(session, principal)


@router.put(
    "/preferences",
    summary="Choose which notifications also come by e-mail",
    responses=problem_responses(422),
)
def update_my_preferences(
    data: PreferencesUpdate, principal: Me, session: Db
) -> list[PreferenceRead]:
    result = service.update_preferences(session, principal, data)
    session.commit()
    return result


@router.post(
    "/{notification_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mark one as read",
    responses=problem_responses(404),
)
def read_one(notification_id: uuid.UUID, principal: Me, session: Db) -> Response:
    service.mark_read(session, principal, notification_id)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
