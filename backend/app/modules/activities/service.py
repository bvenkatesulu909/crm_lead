"""Activity and task business rules. Functions here never commit: the router commits once.

- An activity may be linked to one record the user can SEE (else 404, like a missing record).
- The assignee must be an active staff member of the tenant; giving work to someone else
  needs ``activity:assign`` (managers, admins).
- Only open items can be edited, completed or cancelled; done/cancelled items can be reopened.
- Reassignments are written to the audit log.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.errors import ConflictError, DomainError, ForbiddenError, NotFoundError
from app.core.events import publish as publish_event
from app.modules.accounts import api as accounts_api
from app.modules.activities import repository
from app.modules.activities.models import Activity
from app.modules.activities.repository import ActivityFilters
from app.modules.activities.schemas import ActivityCreate, ActivityRead, ActivityUpdate, Reminders
from app.modules.contacts import api as contacts_api
from app.modules.identity import api as identity_api
from app.modules.leads import api as leads_api
from app.modules.sales import api as sales_api

ENTITY = "activity"


class ActivityNotFoundError(NotFoundError):
    code = "activity_not_found"

    def __init__(self) -> None:
        super().__init__("Activity not found.")


class RelatedNotFoundError(NotFoundError):
    code = "related_not_found"


class VersionConflictError(ConflictError):
    code = "version_conflict"


class ActivityStateError(ConflictError):
    code = "activity_state"


class InvalidActivityError(DomainError):
    status_code = 422
    code = "invalid_activity"


def _tenant(principal: Principal) -> uuid.UUID:
    if principal.tenant_id is None or principal.user_type != "staff":
        raise ForbiddenError("Only staff of an organisation can work with activities.")
    return principal.tenant_id


def _flush(session: Session) -> None:
    try:
        session.flush()
    except StaleDataError as exc:
        raise VersionConflictError(
            "The activity was changed by someone else. Reload it and try again."
        ) from exc


def _check_related(session: Session, principal: Principal, data: ActivityCreate) -> None:
    checks = (
        (data.lead_id, leads_api.is_readable_lead, "Lead"),
        (data.account_id, accounts_api.is_readable_account, "Account"),
        (data.contact_id, contacts_api.is_readable_contact, "Contact"),
        (data.opportunity_id, sales_api.is_readable_opportunity, "Opportunity"),
    )
    for record_id, readable, label in checks:
        if record_id is not None and not readable(session, principal, record_id):
            raise RelatedNotFoundError(f"{label} not found.")


def _check_assignee(session: Session, principal: Principal, assignee_id: uuid.UUID) -> None:
    if assignee_id != principal.user_id and not principal.has_permission(
        Permission.ACTIVITY_ASSIGN
    ):
        raise ForbiddenError("You may not give tasks to other people.")
    if not identity_api.is_active_staff_member(session, _tenant(principal), assignee_id):
        raise InvalidActivityError("The assignee must be an active colleague in your organisation.")


def _load_for_write(session: Session, principal: Principal, activity_id: uuid.UUID) -> Activity:
    activity = repository.get_writable(session, principal, activity_id)
    if activity is None:
        if repository.get_readable(session, principal, activity_id) is not None:
            raise ForbiddenError("You may view this activity but not change it.")
        raise ActivityNotFoundError()
    return activity


def _check(activity: Activity, version: int, *, must_be_open: bool) -> None:
    if activity.version != version:
        raise VersionConflictError(
            f"The activity was changed by someone else (now version {activity.version}). Reload it."
        )
    if must_be_open and activity.status != "open":
        raise ActivityStateError(f"This activity is already {activity.status}.")


def to_read(activity: Activity) -> ActivityRead:
    return ActivityRead.model_validate(activity)


# --- use cases --------------------------------------------------------------------------


def create_activity(session: Session, principal: Principal, data: ActivityCreate) -> Activity:
    tenant_id = _tenant(principal)
    _check_related(session, principal, data)
    assignee_id = data.assignee_id or principal.user_id
    if assignee_id is None:
        raise ForbiddenError("Only users with a CRM account can own activities.")
    _check_assignee(session, principal, assignee_id)
    status = data.status or "open"  # the schema already resolved the default
    activity = Activity(
        tenant_id=tenant_id,
        created_by_user_id=principal.user_id,
        assignee_id=assignee_id,
        status=status,
        completed_at=(data.occurred_at or datetime.now(UTC)) if status == "done" else None,
        **data.model_dump(exclude={"assignee_id", "status", "occurred_at"}),
    )
    session.add(activity)
    _flush(session)
    _announce_assignment(session, principal, activity)
    return activity


def _announce_assignment(session: Session, principal: Principal, activity: Activity) -> None:
    # Only open work for someone else is news; logging your own call is not.
    if activity.status == "open" and activity.assignee_id != principal.user_id:
        publish_event(
            session,
            activity.tenant_id,
            "activity.assigned",
            {
                "activity_id": str(activity.id),
                "assignee_id": str(activity.assignee_id),
                "actor_id": str(principal.user_id) if principal.user_id else None,
            },
        )


def get_activity(session: Session, principal: Principal, activity_id: uuid.UUID) -> Activity:
    activity = repository.get_readable(session, principal, activity_id)
    if activity is None:
        raise ActivityNotFoundError()
    return activity


def list_activities(
    session: Session, principal: Principal, filters: ActivityFilters
) -> tuple[Sequence[Activity], int]:
    return repository.search(session, principal, filters)


def update_activity(
    session: Session, principal: Principal, activity_id: uuid.UUID, data: ActivityUpdate
) -> Activity:
    activity = _load_for_write(session, principal, activity_id)
    _check(activity, data.version, must_be_open=True)
    changes = data.changes()
    if "assignee_id" in changes and changes["assignee_id"] != activity.assignee_id:
        if data.assignee_id is not None:
            _check_assignee(session, principal, data.assignee_id)
        record_audit(
            session,
            principal,
            action="activity.reassigned",
            entity_type=ENTITY,
            entity_id=activity.id,
            changes={"assignee_id": {"old": activity.assignee_id, "new": data.assignee_id}},
        )
    reassigned = "assignee_id" in changes and changes["assignee_id"] != activity.assignee_id
    if "reminder_at" in changes and changes["reminder_at"] != activity.reminder_at:
        activity.reminder_sent_at = None  # a new reminder time means a new reminder
    for field, value in changes.items():
        setattr(activity, field, value)
    if activity.reminder_at and activity.due_at and activity.reminder_at > activity.due_at:
        raise InvalidActivityError("The reminder must be before the due date.")
    _flush(session)
    if reassigned:
        _announce_assignment(session, principal, activity)
    return activity


def complete(
    session: Session,
    principal: Principal,
    activity_id: uuid.UUID,
    *,
    version: int,
    outcome: str | None,
) -> Activity:
    activity = _load_for_write(session, principal, activity_id)
    _check(activity, version, must_be_open=True)
    activity.status = "done"
    activity.completed_at = datetime.now(UTC)
    activity.outcome = outcome
    _flush(session)
    return activity


def cancel(
    session: Session,
    principal: Principal,
    activity_id: uuid.UUID,
    *,
    version: int,
    reason: str | None,
) -> Activity:
    activity = _load_for_write(session, principal, activity_id)
    _check(activity, version, must_be_open=True)
    activity.status = "cancelled"
    activity.outcome = reason
    _flush(session)
    return activity


def reopen(
    session: Session, principal: Principal, activity_id: uuid.UUID, *, version: int
) -> Activity:
    activity = _load_for_write(session, principal, activity_id)
    _check(activity, version, must_be_open=False)
    if activity.status == "open":
        raise ActivityStateError("This activity is already open.")
    if activity.kind == "note":
        raise ActivityStateError("A note cannot be reopened.")
    activity.status = "open"
    activity.completed_at = None
    activity.outcome = None
    _flush(session)
    return activity


def reminders(session: Session, principal: Principal) -> Reminders:
    """The signed-in user's own open items that need attention now.

    Time windows are absolute moments (now, now + 24 h), so they are right in every time zone.
    """
    if principal.user_id is None:
        return Reminders(overdue=0, due_next_24h=0, reminders_due=0, attention=0, items=[])
    now = datetime.now(UTC)
    mine = repository.filtered(
        principal, ActivityFilters(assignee_id=principal.user_id, statuses=("open",))
    )

    def count(condition: ColumnElement[bool]) -> int:
        return (
            session.scalar(select(func.count()).select_from(mine.where(condition).subquery())) or 0
        )

    overdue = Activity.due_at < now
    soon = and_(Activity.due_at >= now, Activity.due_at < now + timedelta(hours=24))
    reminded = Activity.reminder_at <= now
    urgent = session.scalars(
        mine.where(or_(overdue, soon, reminded))
        .order_by(Activity.due_at.asc().nulls_last(), Activity.id)
        .limit(10)
    ).all()
    return Reminders(
        overdue=count(overdue),
        due_next_24h=count(soon),
        reminders_due=count(reminded),
        attention=count(or_(overdue, soon, reminded)),
        items=[to_read(a) for a in urgent],
    )
