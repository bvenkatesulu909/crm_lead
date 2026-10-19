"""Database queries for activities. Every query goes through the activity policies."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.search import escape_like
from app.modules.activities.models import Activity
from app.modules.activities.policies import readable_activities, writable_activities


@dataclass(frozen=True)
class ActivityFilters:
    q: str | None = None
    assignee_id: uuid.UUID | None = None
    statuses: tuple[str, ...] = ()
    kinds: tuple[str, ...] = ()
    due_from: datetime | None = None
    due_to: datetime | None = None
    overdue_at: datetime | None = None  # open and due before this moment
    lead_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None
    sort: str = "due_at"
    limit: int = 50
    offset: int = 0


_SORTS = {
    "due_at": (Activity.due_at.asc().nulls_last(), Activity.created_at.asc()),
    "-completed_at": (Activity.completed_at.desc().nulls_last(), Activity.created_at.desc()),
    "-created_at": (Activity.created_at.desc(),),
    # Timeline of a record: when it happened (done) or is due (open), newest first.
    "-when": (func.coalesce(Activity.completed_at, Activity.due_at, Activity.created_at).desc(),),
}


def filtered(principal: Principal, f: ActivityFilters) -> Select[Activity]:
    statement = select(Activity).where(readable_activities(principal))
    if f.q:
        statement = statement.where(Activity.subject.ilike(f"%{escape_like(f.q)}%", escape="\\"))
    if f.assignee_id:
        statement = statement.where(Activity.assignee_id == f.assignee_id)
    if f.statuses:
        statement = statement.where(Activity.status.in_(f.statuses))
    if f.kinds:
        statement = statement.where(Activity.kind.in_(f.kinds))
    if f.due_from:
        statement = statement.where(Activity.due_at >= f.due_from)
    if f.due_to:
        statement = statement.where(Activity.due_at < f.due_to)
    if f.overdue_at:
        statement = statement.where(Activity.status == "open", Activity.due_at < f.overdue_at)
    for column in ("lead_id", "account_id", "contact_id", "opportunity_id"):
        value = getattr(f, column)
        if value:
            statement = statement.where(getattr(Activity, column) == value)
    return statement


def search(
    session: Session, principal: Principal, f: ActivityFilters
) -> tuple[Sequence[Activity], int]:
    statement = filtered(principal, f)
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    page = statement.order_by(*_SORTS[f.sort], Activity.id).limit(f.limit).offset(f.offset)
    return session.scalars(page).all(), total


def count(session: Session, principal: Principal, f: ActivityFilters) -> int:
    return session.scalar(select(func.count()).select_from(filtered(principal, f).subquery())) or 0


def get_readable(session: Session, principal: Principal, activity_id: uuid.UUID) -> Activity | None:
    return session.scalars(
        select(Activity).where(Activity.id == activity_id, readable_activities(principal))
    ).one_or_none()


def get_writable(session: Session, principal: Principal, activity_id: uuid.UUID) -> Activity | None:
    return session.scalars(
        select(Activity)
        .where(Activity.id == activity_id, writable_activities(principal))
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one_or_none()
