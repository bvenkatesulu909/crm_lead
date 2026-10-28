"""Public interface of the activities module."""

import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, false, func, or_, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.events import publish as publish_event
from app.core.records import RecordFacts
from app.core.reporting import Cell, Column, ExportFilters, ExportSpec, export_rows
from app.modules.activities import repository, service
from app.modules.activities.models import ACTIVITY_STATUSES, PRIORITIES, Activity
from app.modules.activities.policies import readable_activities
from app.modules.activities.schemas import ActivityCreate

__all__ = [
    "EXPORT",
    "export_table",
    "overdue_tasks",
    "create_task",
    "task_snapshot",
    "log_email",
    "activity_facts",
    "ACTIVITY_PRIORITIES",
    "publish_due_reminders",
    "activity_brief",
    "last_interaction_by_account",
    "reassign_open_activities",
]


def _linked(
    account_id: uuid.UUID, contact_ids: list[uuid.UUID], opportunity_ids: list[uuid.UUID]
) -> ColumnElement[bool]:
    """Activities on the account itself, on its contacts or on its deals."""
    return or_(
        Activity.account_id == account_id,
        Activity.contact_id.in_(contact_ids) if contact_ids else false(),
        Activity.opportunity_id.in_(opportunity_ids) if opportunity_ids else false(),
    )


def last_interaction_by_account(
    session: Session,
    tenant_id: uuid.UUID,
    links: dict[uuid.UUID, tuple[list[uuid.UUID], list[uuid.UUID]]],
) -> dict[uuid.UUID, datetime]:
    """When something last HAPPENED with each account: a done call, meeting, e-mail, note or
    task on the account, its contacts or its deals. ``links``: account -> (contacts, deals)."""
    result: dict[uuid.UUID, datetime] = {}
    for account_id, (contact_ids, opportunity_ids) in links.items():
        at = session.scalar(
            select(func.max(Activity.completed_at)).where(
                Activity.tenant_id == tenant_id,
                Activity.status == "done",
                _linked(account_id, contact_ids, opportunity_ids),
            )
        )
        if at is not None:
            result[account_id] = at
    return result


def reassign_open_activities(
    session: Session,
    principal: Principal,
    *,
    account_id: uuid.UUID,
    contact_ids: list[uuid.UUID],
    opportunity_ids: list[uuid.UUID],
    from_user: uuid.UUID,
    to_user: uuid.UUID,
) -> list[uuid.UUID]:
    """Open tasks and follow-ups on the account (or its contacts/deals) that were assigned to
    the previous owner go to the new owner. Each reassignment is audited."""
    items = session.scalars(
        select(Activity)
        .where(
            Activity.tenant_id == principal.tenant_id,
            Activity.status == "open",
            Activity.assignee_id == from_user,
            _linked(account_id, contact_ids, opportunity_ids),
        )
        .with_for_update()
    ).all()
    for item in items:
        item.assignee_id = to_user
        record_audit(
            session,
            principal,
            action="activity.reassigned",
            entity_type="activity",
            entity_id=item.id,
            changes={
                "assignee_id": {"old": from_user, "new": to_user},
                "reason": "Account transfer",
            },
        )
    session.flush()
    return [i.id for i in items]


def activity_brief(
    session: Session, principal: Principal, activity_id: uuid.UUID
) -> tuple[str, str] | None:
    """(subject, page to open) for an activity this principal may see, else None."""
    activity = repository.get_readable(session, principal, activity_id)
    if activity is None:
        return None
    for prefix, record in (
        ("/leads", activity.lead_id),
        ("/opportunities", activity.opportunity_id),
        ("/accounts", activity.account_id),
        ("/contacts", activity.contact_id),
    ):
        if record is not None:
            return activity.subject, f"{prefix}/{record}"
    return activity.subject, "/tasks"


def publish_due_reminders(
    session: Session,
    now: datetime,
    *,
    tenant_id: uuid.UUID | None = None,
    limit: int = 200,
) -> int:
    """Worker scheduler: an "activity.reminder_due" event for every open task whose reminder
    time has come, once per reminder (``reminder_sent_at``). Runs without a user, across
    tenants; each event belongs to its task's tenant."""
    due = session.scalars(
        select(Activity)
        .where(
            Activity.status == "open",
            Activity.reminder_at.is_not(None),
            Activity.reminder_at <= now,
            Activity.reminder_sent_at.is_(None),
            *([Activity.tenant_id == tenant_id] if tenant_id is not None else []),
        )
        .order_by(Activity.reminder_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    for activity in due:
        activity.reminder_sent_at = now
        publish_event(
            session,
            activity.tenant_id,
            "activity.reminder_due",
            {"activity_id": str(activity.id), "assignee_id": str(activity.assignee_id)},
        )
    return len(due)


ACTIVITY_PRIORITIES = PRIORITIES


def activity_facts(
    session: Session, principal: Principal, activity_id: uuid.UUID
) -> RecordFacts | None:
    activity = repository.get_readable(session, principal, activity_id)
    if activity is None:
        return None
    brief = activity_brief(session, principal, activity_id)
    return RecordFacts(
        record_type="activity",
        record_id=activity.id,
        label=activity.subject,
        link=brief[1] if brief else "/tasks",
        owner_id=activity.assignee_id,
        account_id=activity.account_id,
        lead_id=activity.lead_id,
        values={"kind": activity.kind, "priority": activity.priority},
    )


def task_snapshot(
    session: Session, principal: Principal, activity_id: uuid.UUID, today: date
) -> dict[str, Any] | None:
    """A task as the verification artifact (ADR 0018) describes it: its subject, how many days
    from ``today`` it is due and who it is for. None if this principal may not see it."""
    activity = repository.get_readable(session, principal, activity_id)
    if activity is None:
        return None
    due = activity.due_at.date() if activity.due_at is not None else None
    return {
        "subject": activity.subject,
        "due_in_days": (due - today).days if due is not None else None,
        "assignee_id": str(activity.assignee_id) if activity.assignee_id else None,
    }


def overdue_tasks(
    session: Session, tenant_id: uuid.UUID, now: datetime, overdue_days: int
) -> list[tuple[uuid.UUID, datetime]]:
    """(id, due_at) of open tasks overdue by at least ``overdue_days`` days (schedules)."""
    rows = session.execute(
        select(Activity.id, Activity.due_at).where(
            Activity.tenant_id == tenant_id,
            Activity.status == "open",
            Activity.due_at.is_not(None),
            Activity.due_at <= now - timedelta(days=overdue_days),
        )
    ).all()
    return [(row.id, row.due_at) for row in rows if row.due_at is not None]


def create_task(
    session: Session,
    principal: Principal,
    *,
    subject: str,
    due_at: datetime | None,
    assignee_id: uuid.UUID,
    lead_id: uuid.UUID | None,
    account_id: uuid.UUID | None,
    contact_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Create an open task with the activities module's own checks (links, assignee, audit).
    Linked to one record: the lead if given, else the contact, else the account."""
    activity = service.create_activity(
        session,
        principal,
        ActivityCreate(
            kind="task",
            subject=subject[:200],
            due_at=due_at,
            assignee_id=assignee_id,
            lead_id=lead_id,
            contact_id=contact_id if lead_id is None else None,
            account_id=account_id if lead_id is None and contact_id is None else None,
        ),
    )
    return activity.id


def log_email(
    session: Session,
    principal: Principal,
    *,
    subject: str,
    lead_id: uuid.UUID | None,
    contact_id: uuid.UUID | None,
    received: bool = False,
) -> uuid.UUID:
    """A "done" e-mail entry on the lead's or contact's timeline (Communication Center).

    Only the subject is copied; the text itself stays with the message (ADR 0012)."""
    activity = service.create_activity(
        session,
        principal,
        ActivityCreate(
            kind="email",
            subject=f"{'E-mail received' if received else 'E-mail'}: {subject}"[:200],
            status="done",
            lead_id=lead_id,
            contact_id=contact_id if lead_id is None else None,
        ),
    )
    return activity.id


# Report builder (Phase 18): the columns that may be exported - never internal notes - and the
# statuses to filter by. Rows always pass through this module's own record-level policy.
EXPORT = ExportSpec(
    columns=(
        Column("created_at", "Created", "datetime"),
        Column("kind", "Kind", "text"),
        Column("subject", "Subject", "text"),
        Column("status", "Status", "text"),
        Column("priority", "Priority", "text"),
        Column("due_at", "Due", "datetime"),
        Column("completed_at", "Completed", "datetime"),
        Column("assignee_id", "Assignee", "user"),
    ),
    statuses=ACTIVITY_STATUSES,
)


def export_table(
    session: Session, principal: Principal, filters: ExportFilters, wanted: list[str]
) -> list[dict[str, Cell]]:
    allowed = {c.key for c in EXPORT.columns}
    if not wanted or not set(wanted) <= allowed:
        raise ValueError("unknown export column")
    return export_rows(
        session,
        entity=Activity,
        columns={key: getattr(Activity, key) for key in allowed},
        wanted=wanted,
        condition=readable_activities(principal),
        created=Activity.created_at,
        owner=Activity.assignee_id,
        status=Activity.status,
        filters=filters,
    )
