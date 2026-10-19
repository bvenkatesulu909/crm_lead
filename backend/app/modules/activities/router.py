"""Activity and task endpoints, mounted at /api/v1/activities.

Thin layer: check the caller's coarse permission (RBAC), call the service, commit once.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import DomainError, problem_responses
from app.modules.activities import service
from app.modules.activities.repository import ActivityFilters
from app.modules.activities.schemas import (
    ActivityCreate,
    ActivityPage,
    ActivityRead,
    ActivityUpdate,
    Cancel,
    Complete,
    Kind,
    Reminders,
    Reopen,
    Status,
)
from app.modules.identity.api import require_any_permission

router = APIRouter(prefix="/activities", tags=["activities"], responses=problem_responses(401, 403))
Reader = Annotated[
    Principal,
    Depends(require_any_permission(Permission.ACTIVITY_READ_ALL, Permission.ACTIVITY_READ_OWN)),
]
Writer = Annotated[
    Principal,
    Depends(require_any_permission(Permission.ACTIVITY_WRITE_ALL, Permission.ACTIVITY_WRITE_OWN)),
]
Db = Annotated[Session, Depends(get_db_session)]


class InvalidFilterError(DomainError):
    status_code = 422
    code = "invalid_filter"


def _aware(value: datetime | None, name: str) -> datetime | None:
    if value is not None and value.tzinfo is None:
        raise InvalidFilterError(f"{name} must include a time zone, e.g. 2026-10-19T00:00:00Z")
    return value


@router.get(
    "",
    summary="List activities and tasks you may see",
    description="`mine=true` = assigned to you. `overdue=true` = open and past due. "
    "`due_from`/`due_to` (with time zone) select a calendar range. Link filters "
    "(`lead_id`, `account_id`, `contact_id`, `opportunity_id`) give a record's timeline.",
)
def list_activities(
    principal: Reader,
    session: Db,
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    mine: bool = False,
    assignee_id: uuid.UUID | None = None,
    status: Annotated[list[Status] | None, Query()] = None,
    kind: Annotated[list[Kind] | None, Query()] = None,
    due_from: datetime | None = None,
    due_to: datetime | None = None,
    overdue: bool = False,
    lead_id: uuid.UUID | None = None,
    account_id: uuid.UUID | None = None,
    contact_id: uuid.UUID | None = None,
    opportunity_id: uuid.UUID | None = None,
    sort: Literal["due_at", "-completed_at", "-created_at", "-when"] = "due_at",
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=100_000),
) -> ActivityPage:
    filters = ActivityFilters(
        q=q.strip() if q else None,
        assignee_id=principal.user_id if mine else assignee_id,
        statuses=tuple(status or ()),
        kinds=tuple(kind or ()),
        due_from=_aware(due_from, "due_from"),
        due_to=_aware(due_to, "due_to"),
        overdue_at=datetime.now(UTC) if overdue else None,
        lead_id=lead_id,
        account_id=account_id,
        contact_id=contact_id,
        opportunity_id=opportunity_id,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    items, total = service.list_activities(session, principal, filters)
    return ActivityPage(
        items=[service.to_read(a) for a in items], total=total, limit=limit, offset=offset
    )


@router.get(
    "/reminders",
    summary="Your open items that need attention (overdue, due within 24 h, reminder passed)",
)
def get_reminders(principal: Reader, session: Db) -> Reminders:
    return service.reminders(session, principal)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a task or follow-up, or log a call / meeting / e-mail / note",
    responses=problem_responses(404, 422),
)
def create_activity(
    data: ActivityCreate, principal: Writer, session: Db, response: Response
) -> ActivityRead:
    activity = service.create_activity(session, principal, data)
    session.commit()
    response.headers["Location"] = f"/api/v1/activities/{activity.id}"
    return service.to_read(activity)


@router.get("/{activity_id}", summary="Get one activity", responses=problem_responses(404))
def get_activity(activity_id: uuid.UUID, principal: Reader, session: Db) -> ActivityRead:
    return service.to_read(service.get_activity(session, principal, activity_id))


@router.patch(
    "/{activity_id}",
    summary="Change an open activity (subject, due date, reminder, priority, assignee)",
    responses=problem_responses(404, 409, 422),
)
def update_activity(
    activity_id: uuid.UUID, data: ActivityUpdate, principal: Writer, session: Db
) -> ActivityRead:
    activity = service.update_activity(session, principal, activity_id, data)
    session.commit()
    return service.to_read(activity)


@router.post(
    "/{activity_id}/complete", summary="Mark as done", responses=problem_responses(404, 409)
)
def complete(
    activity_id: uuid.UUID, data: Complete, principal: Writer, session: Db
) -> ActivityRead:
    activity = service.complete(
        session, principal, activity_id, version=data.version, outcome=data.outcome
    )
    session.commit()
    return service.to_read(activity)


@router.post("/{activity_id}/cancel", summary="Cancel", responses=problem_responses(404, 409))
def cancel(activity_id: uuid.UUID, data: Cancel, principal: Writer, session: Db) -> ActivityRead:
    activity = service.cancel(
        session, principal, activity_id, version=data.version, reason=data.reason
    )
    session.commit()
    return service.to_read(activity)


@router.post("/{activity_id}/reopen", summary="Reopen", responses=problem_responses(404, 409))
def reopen(activity_id: uuid.UUID, data: Reopen, principal: Writer, session: Db) -> ActivityRead:
    activity = service.reopen(session, principal, activity_id, version=data.version)
    session.commit()
    return service.to_read(activity)
