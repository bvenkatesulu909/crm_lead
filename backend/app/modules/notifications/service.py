"""Notifications (ADR 0006, step 17a). Functions here never commit: the router (or the worker)
commits once.

How a notification is made:
1. A module publishes a domain event (e.g. "lead.assigned").
2. ``on_event`` (run by the worker) decides WHO should hear about it, checks that each person
   is an active colleague who may SEE the record (through the owning module's api.py), and
   writes one row per person. The same event never makes two rows for one person.
3. If the person wants e-mails for this type, a "notification.email" job sends one.
The person who caused the event is never notified about it.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission, Role
from app.core.errors import DomainError, NotFoundError
from app.core.events import Event, uuid_of
from app.core.mail import Mail, Mailer
from app.core.outbox import PermanentJobError, enqueue
from app.modules.activities import api as activities_api
from app.modules.communications import api as communications_api
from app.modules.contracts import api as contracts_api
from app.modules.identity import api as identity_api
from app.modules.leads import api as leads_api
from app.modules.notifications.models import Notification, NotificationPreference
from app.modules.notifications.schemas import (
    NotificationPage,
    NotificationRead,
    PreferenceRead,
    PreferencesUpdate,
)
from app.modules.quotes import api as quotes_api
from app.modules.support import api as support_api

EMAIL_JOB = "notification.email"

# Notification types (= event names) and how they are described on the settings page.
TYPES: dict[str, str] = {
    "activity.reminder_due": "Reminders for your tasks",
    "activity.assigned": "A task was assigned to you",
    "lead.assigned": "A lead was assigned to you",
    "quote.approval_requested": "A quote is waiting for your approval",
    "quote.approved": "Your quote was approved",
    "quote.rejected": "Your quote was returned to draft",
    "quote.accepted": "A customer accepted your quote",
    "quote.declined": "A customer declined your quote",
    "ticket.assigned": "A ticket was assigned to you",
    "ticket.customer_replied": "A customer replied on your ticket",
    "contract.renewal_due": "A contract of yours is coming up for renewal",
    "contract.expired": "A contract of yours has expired",
    "communication.email_failed": "An e-mail you wrote could not be delivered",
    "workflow.message": "A message from an automation rule",
}
RULE_MESSAGE = "workflow.message"
EMAIL_BY_DEFAULT = frozenset(
    {"activity.reminder_due", "quote.approval_requested", "quote.accepted", "contract.renewal_due"}
)


class InvalidPreferenceError(DomainError):
    status_code = 422
    code = "invalid_preference"


class NotificationNotFoundError(NotFoundError):
    code = "notification_not_found"

    def __init__(self) -> None:
        super().__init__("The notification doesn't exist.")


def _me(principal: Principal) -> tuple[uuid.UUID, uuid.UUID]:
    if principal.tenant_id is None or principal.user_id is None:
        raise NotificationNotFoundError()
    return principal.tenant_id, principal.user_id


# --- turning events into notifications (worker) ------------------------------------------


@dataclass(frozen=True)
class Draft:
    title: str
    link: str


# Who may hear about an event: user ids from the event plus record facts, without the actor.
Describe = Callable[[Session, Principal, Event], Draft | None]


def _optional_uuid(event: Event, key: str) -> uuid.UUID | None:
    value = event.data.get(key)
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def _lead(session: Session, me: Principal, event: Event) -> Draft | None:
    lead_id = uuid_of(event, "lead_id")
    label = leads_api.lead_brief(session, me, lead_id)
    return Draft(f"Lead assigned to you: {label}", f"/leads/{lead_id}") if label else None


def _activity(prefix: str) -> Describe:
    def describe(session: Session, me: Principal, event: Event) -> Draft | None:
        brief = activities_api.activity_brief(session, me, uuid_of(event, "activity_id"))
        return Draft(f"{prefix}: {brief[0]}", brief[1]) if brief else None

    return describe


def _quote(prefix: str) -> Describe:
    def describe(session: Session, me: Principal, event: Event) -> Draft | None:
        quote_id = uuid_of(event, "quote_id")
        brief = quotes_api.quote_brief(session, me, quote_id)
        return Draft(f"{prefix}: {brief[0]}", f"/quotes/{quote_id}") if brief else None

    return describe


def _contract(prefix: str) -> Describe:
    def describe(session: Session, me: Principal, event: Event) -> Draft | None:
        contract_id = uuid_of(event, "contract_id")
        brief = contracts_api.contract_brief(session, me, contract_id)
        return Draft(f"{prefix}: {brief[0]}", f"/contracts/{contract_id}") if brief else None

    return describe


def _email(session: Session, me: Principal, event: Event) -> Draft | None:
    brief = communications_api.message_brief(session, me, uuid_of(event, "message_id"))
    return Draft(f"E-mail not delivered: {brief[0]}", brief[1]) if brief else None


def _ticket(prefix: str) -> Describe:
    def describe(session: Session, me: Principal, event: Event) -> Draft | None:
        ticket_id = uuid_of(event, "ticket_id")
        brief = support_api.ticket_brief(session, me, ticket_id)
        return Draft(f"{prefix}: {brief[0]}", f"/tickets/{ticket_id}") if brief else None

    return describe


def _quote_people(session: Session, event: Event) -> set[uuid.UUID]:
    """Owner and creator of the quote (each is still checked: may they see it?)."""
    return quotes_api.quote_people(session, event.tenant_id, uuid_of(event, "quote_id"))


def _contract_people(session: Session, event: Event) -> set[uuid.UUID]:
    """Owner and creator of the contract (each is still checked: may they see it?)."""
    return contracts_api.contract_people(session, event.tenant_id, uuid_of(event, "contract_id"))


def _approvers(session: Session, event: Event) -> set[uuid.UUID]:
    """Everyone who may approve - except the quote's owner/creator (four-eyes), unless admin."""
    owners = _quote_people(session, event)
    result = set()
    for user_id in identity_api.staff_with_permission(
        session, event.tenant_id, Permission.QUOTE_APPROVE
    ):
        me = identity_api.staff_principal(session, event.tenant_id, user_id)
        if me and (user_id not in owners or Role.TENANT_ADMIN in me.roles):
            result.add(user_id)
    return result


def _assignee(session: Session, event: Event) -> set[uuid.UUID]:
    person = _optional_uuid(event, "assignee_id")
    return {person} if person else set()


def _sender(session: Session, event: Event) -> set[uuid.UUID]:
    person = _optional_uuid(event, "sender_id")
    return {person} if person else set()


def _ticket_assignee(session: Session, event: Event) -> set[uuid.UUID]:
    person = support_api.ticket_assignee(session, event.tenant_id, uuid_of(event, "ticket_id"))
    return {person} if person else set()


Recipients = Callable[[Session, Event], set[uuid.UUID]]
RULES: dict[str, tuple[Recipients, Describe]] = {
    "lead.assigned": (_assignee, _lead),
    "activity.assigned": (_assignee, _activity("New task for you")),
    "activity.reminder_due": (_assignee, _activity("Reminder")),
    "quote.approval_requested": (_approvers, _quote("Approval needed")),
    "quote.approved": (_quote_people, _quote("Quote approved")),
    "quote.rejected": (_quote_people, _quote("Quote returned to draft")),
    "quote.accepted": (_quote_people, _quote("Customer accepted")),
    "quote.declined": (_quote_people, _quote("Customer declined")),
    "ticket.assigned": (_assignee, _ticket("Ticket assigned to you")),
    "ticket.customer_replied": (_ticket_assignee, _ticket("Customer replied")),
    "contract.renewal_due": (_contract_people, _contract("Renewal due")),
    "contract.expired": (_contract_people, _contract("Contract expired")),
    "communication.email_failed": (_sender, _email),
}


def _write(
    session: Session,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    kind: str,
    draft: Draft,
    key: uuid.UUID,
) -> bool:
    """One notification (at most once per person and key) and, if wanted, its e-mail job."""
    new_id = session.scalar(
        insert(Notification)
        .values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            user_id=user_id,
            type=kind,
            title=draft.title[:300],
            link=draft.link[:300],
            event_id=key,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "user_id", "event_id"])
        .returning(Notification.id)
    )
    if new_id is None:
        return False
    if _wants_email(session, tenant_id, user_id, kind):
        enqueue(
            session, tenant_id=tenant_id, kind=EMAIL_JOB, payload={"notification_id": str(new_id)}
        )
    return True


def notify_users(
    session: Session,
    tenant_id: uuid.UUID,
    user_ids: set[uuid.UUID],
    *,
    title: str,
    link: str,
    key: uuid.UUID,
    can_see: Callable[[Principal], bool],
) -> int:
    """Messages from workflow rules. Each person must be active staff and allowed to see the
    record (``can_see`` asks the owning module); ``key`` makes repeats harmless."""
    made = 0
    for user_id in sorted(user_ids):
        me = identity_api.staff_principal(session, tenant_id, user_id)
        if me is None or not can_see(me):
            continue
        made += _write(session, tenant_id, user_id, RULE_MESSAGE, Draft(title, link), key)
    return made


def _wants_email(session: Session, tenant_id: uuid.UUID, user_id: uuid.UUID, kind: str) -> bool:
    choice = session.scalar(
        select(NotificationPreference.email).where(
            NotificationPreference.tenant_id == tenant_id,
            NotificationPreference.user_id == user_id,
            NotificationPreference.type == kind,
        )
    )
    return kind in EMAIL_BY_DEFAULT if choice is None else choice


def on_event(session: Session, event: Event) -> int:
    """Subscriber for every event in RULES. Returns how many notifications were made."""
    rule = RULES.get(event.name)
    if rule is None:
        return 0
    recipients, describe = rule
    actor = _optional_uuid(event, "actor_id")
    made = 0
    for user_id in sorted(recipients(session, event) - {actor}):
        me = identity_api.staff_principal(session, event.tenant_id, user_id)
        if me is None:
            continue  # left the company, or not staff
        draft = describe(session, me, event)
        if draft is None:
            continue  # may not see the record: never told about it
        # False when delivered before (the worker retried): nothing new.
        made += _write(session, event.tenant_id, user_id, event.name, draft, event.id)
    return made


def send_email(
    session: Session,
    mailer: Mailer,
    tenant_id: uuid.UUID,
    notification_id: uuid.UUID,
    web_app_url: str,
) -> None:
    note = session.scalars(
        select(Notification).where(
            Notification.tenant_id == tenant_id, Notification.id == notification_id
        )
    ).one_or_none()
    if note is None:
        raise PermanentJobError("notification not found")
    me = identity_api.staff_principal(session, tenant_id, note.user_id)
    if me is None or not me.email:
        raise PermanentJobError("recipient no longer active")
    base = web_app_url.rstrip("/")
    mailer.send(
        Mail(
            to=(me.email,),
            subject=note.title,
            text="\n".join(
                [
                    f"Hello {me.display_name or ''},".replace(" ,", ","),
                    "",
                    note.title,
                    "",
                    f"Open it in the CRM: {base}{note.link}",
                    "",
                    f"Choose which e-mails you get: {base}/notifications/settings",
                ]
            ),
        )
    )


# --- the person's own notifications (API) ------------------------------------------------


def list_notifications(
    session: Session, principal: Principal, *, unread_only: bool, limit: int
) -> NotificationPage:
    tenant_id, user_id = _me(principal)
    mine = (Notification.tenant_id == tenant_id) & (Notification.user_id == user_id)
    query = select(Notification).where(mine)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    items = session.scalars(
        query.order_by(Notification.created_at.desc(), Notification.id).limit(limit)
    ).all()
    unread = session.scalar(
        select(func.count()).select_from(Notification).where(mine, Notification.read_at.is_(None))
    )
    return NotificationPage(
        items=[NotificationRead.model_validate(n) for n in items], unread=unread or 0
    )


def mark_read(session: Session, principal: Principal, notification_id: uuid.UUID) -> None:
    tenant_id, user_id = _me(principal)
    note = session.scalars(
        select(Notification).where(
            Notification.tenant_id == tenant_id,
            Notification.user_id == user_id,  # someone else's notification: 404
            Notification.id == notification_id,
        )
    ).one_or_none()
    if note is None:
        raise NotificationNotFoundError()
    if note.read_at is None:
        note.read_at = func.now()
    session.flush()


def mark_all_read(session: Session, principal: Principal) -> None:
    tenant_id, user_id = _me(principal)
    session.execute(
        update(Notification)
        .where(
            Notification.tenant_id == tenant_id,
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
        )
        .values(read_at=func.now())
    )


def preferences(session: Session, principal: Principal) -> list[PreferenceRead]:
    tenant_id, user_id = _me(principal)
    chosen = dict(
        session.execute(
            select(NotificationPreference.type, NotificationPreference.email).where(
                NotificationPreference.tenant_id == tenant_id,
                NotificationPreference.user_id == user_id,
            )
        ).all()
    )
    return [
        PreferenceRead(type=kind, label=label, email=chosen.get(kind, kind in EMAIL_BY_DEFAULT))
        for kind, label in TYPES.items()
    ]


def update_preferences(
    session: Session, principal: Principal, data: PreferencesUpdate
) -> list[PreferenceRead]:
    tenant_id, user_id = _me(principal)
    for item in data.items:
        if item.type not in TYPES:
            raise InvalidPreferenceError(f"Unknown notification type {item.type!r}.")
        session.execute(
            insert(NotificationPreference)
            .values(tenant_id=tenant_id, user_id=user_id, type=item.type, email=item.email)
            .on_conflict_do_update(
                index_elements=["tenant_id", "user_id", "type"], set_={"email": item.email}
            )
        )
    return preferences(session, principal)
