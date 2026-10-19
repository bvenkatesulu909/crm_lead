"""Ticket business rules. Functions never commit; routers commit once per request.

Every important change writes an audit_log row in the same transaction.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal, cast

from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.errors import ConflictError, DomainError, ForbiddenError, NotFoundError
from app.core.events import publish as publish_event
from app.modules.accounts import api as accounts_api
from app.modules.identity import api as identity_api
from app.modules.support import repository
from app.modules.support.models import Ticket, TicketComment
from app.modules.support.policies import can_manage
from app.modules.support.repository import TicketFilters
from app.modules.support.rules import check_transition, due_times, sla_state
from app.modules.support.schemas import (
    CommentRead,
    PortalCommentRead,
    PortalTicketRead,
    TicketRead,
)

ENTITY = "ticket"


class TicketNotFoundError(NotFoundError):
    code = "ticket_not_found"

    def __init__(self) -> None:
        super().__init__("Ticket not found.")


class TicketClosedError(ConflictError):
    code = "ticket_closed"


class VersionConflictError(ConflictError):
    code = "version_conflict"


class InvalidAssigneeError(DomainError):
    status_code = 422
    code = "invalid_assignee"


def _now() -> datetime:
    return datetime.now(UTC)


def _tenant(principal: Principal) -> uuid.UUID:
    if principal.tenant_id is None:
        raise ForbiddenError("Only members of an organisation can use support tickets.")
    return principal.tenant_id


def _flush(session: Session) -> None:
    try:
        session.flush()
    except StaleDataError as exc:
        raise VersionConflictError("The ticket was changed by someone else. Reload it.") from exc


def _audit(
    session: Session, principal: Principal, ticket: Ticket, action: str, changes: dict[str, object]
) -> None:
    record_audit(
        session, principal, action=action, entity_type=ENTITY, entity_id=ticket.id, changes=changes
    )


def to_staff_view(ticket: Ticket, now: datetime | None = None) -> TicketRead:
    state = sla_state(
        status=ticket.status,
        now=now or _now(),
        created_at=ticket.created_at,
        first_response_due_at=ticket.first_response_due_at,
        resolution_due_at=ticket.resolution_due_at,
        first_responded_at=ticket.first_responded_at,
        resolved_at=ticket.resolved_at,
    )
    return TicketRead.model_validate({**_columns(ticket), "sla_state": state})


def _columns(ticket: Ticket) -> dict[str, object]:
    return {c.key: getattr(ticket, c.key) for c in Ticket.__table__.columns}


def to_portal_view(ticket: Ticket) -> PortalTicketRead:
    return PortalTicketRead.model_validate(ticket)


# --- create -------------------------------------------------------------------------------


def _create(
    session: Session,
    principal: Principal,
    *,
    account_id: uuid.UUID,
    subject: str,
    description: str,
    priority: str,
    channel: str,
    requester_user_id: uuid.UUID | None,
    category: str = "question",
) -> Ticket:
    tenant_id = _tenant(principal)
    # The account must be visible to the caller: a customer's own granted account, or (staff)
    # an account their role can read. Anything else looks like a missing account.
    if not accounts_api.is_readable_account(session, principal, account_id):
        raise NotFoundError("Account not found.")
    now = _now()
    first_due, resolution_due = due_times(priority, now)
    ticket = Ticket(
        tenant_id=tenant_id,
        number=repository.next_ticket_number(session, tenant_id),
        account_id=account_id,
        requester_user_id=requester_user_id,
        subject=subject,
        description=description,
        priority=priority,
        channel=channel,
        category=category,
        first_response_due_at=first_due,
        resolution_due_at=resolution_due,
        created_at=now,
        updated_at=now,
    )
    session.add(ticket)
    session.flush()
    _audit(
        session,
        principal,
        ticket,
        "ticket.created",
        {
            "number": ticket.number,
            "account_id": account_id,
            "channel": channel,
            "priority": priority,
            "category": category,
        },
    )
    _flush(session)
    return ticket


def create_staff_ticket(
    session: Session,
    principal: Principal,
    *,
    account_id: uuid.UUID,
    subject: str,
    description: str,
    priority: str,
    category: str = "question",
) -> Ticket:
    if not can_manage(principal):
        raise ForbiddenError("You may not create tickets.")
    return _create(
        session,
        principal,
        account_id=account_id,
        subject=subject,
        description=description,
        priority=priority,
        channel="staff",
        requester_user_id=None,
        category=category,
    )


def create_customer_ticket(
    session: Session,
    principal: Principal,
    *,
    account_id: uuid.UUID,
    subject: str,
    description: str,
    channel: str = "portal",
    priority: str = "normal",
    category: str = "question",
) -> Ticket:
    """A customer asks for help - from the portal, or via the AI assistant's human handoff
    (channel="assistant"). Runs AS the customer: only their granted accounts are accepted."""
    if principal.user_type != "customer" or not principal.has_permission(
        Permission.PORTAL_TICKET_WRITE
    ):
        raise ForbiddenError("Only customers can open tickets here.")
    if channel not in ("portal", "assistant"):
        raise ValueError(f"invalid customer channel {channel!r}")
    return _create(
        session,
        principal,
        account_id=account_id,
        subject=subject,
        description=description,
        priority=priority,
        channel=channel,
        requester_user_id=principal.user_id,
        category=category,
    )


# --- read ---------------------------------------------------------------------------------


def get_ticket(session: Session, principal: Principal, ticket_id: uuid.UUID) -> Ticket:
    ticket = repository.get_readable(session, principal, ticket_id)
    if ticket is None:
        raise TicketNotFoundError()
    return ticket


def list_tickets(
    session: Session, principal: Principal, filters: TicketFilters
) -> tuple[Sequence[Ticket], int]:
    return repository.search(session, principal, filters, _now())


AuthorType = Literal["staff", "customer", "system"]


def _comment_authors(
    session: Session, ticket: Ticket, items: Sequence[TicketComment]
) -> dict[uuid.UUID, tuple[str, str]]:
    ids = {c.author_user_id for c in items if c.author_user_id is not None}
    return identity_api.people_by_id(session, ticket.tenant_id, ids)


def _author(
    people: dict[uuid.UUID, tuple[str, str]], author_id: uuid.UUID | None, unknown: str
) -> tuple[str, AuthorType]:
    if author_id is None:
        return "System", "system"
    name, user_type = people.get(author_id, (unknown, "staff"))
    return name, "customer" if user_type == "customer" else "staff"


def staff_comments(
    session: Session, principal: Principal, ticket_id: uuid.UUID
) -> list[CommentRead]:
    ticket = get_ticket(session, principal, ticket_id)
    items = repository.comments(session, ticket, include_internal=True)
    people = _comment_authors(session, ticket, items)
    views = []
    for c in items:
        name, kind = _author(people, c.author_user_id, "Former user")
        views.append(
            CommentRead(
                id=c.id,
                ticket_id=c.ticket_id,
                body=c.body,
                visibility=cast(Literal["public", "internal"], c.visibility),
                author_user_id=c.author_user_id,
                author_name=name,
                author_type=kind,
                created_at=c.created_at,
            )
        )
    return views


def portal_comments(
    session: Session, principal: Principal, ticket_id: uuid.UUID
) -> list[PortalCommentRead]:
    ticket = get_ticket(session, principal, ticket_id)
    items = repository.comments(session, ticket, include_internal=False)  # never internal notes
    people = _comment_authors(session, ticket, items)
    views = []
    for c in items:
        name, kind = _author(people, c.author_user_id, "Support team")
        views.append(
            PortalCommentRead(
                id=c.id, body=c.body, author_name=name, author_type=kind, created_at=c.created_at
            )
        )
    return views


# --- change (staff) -----------------------------------------------------------------------


def _load_for_change(session: Session, principal: Principal, ticket_id: uuid.UUID) -> Ticket:
    ticket = repository.get_readable(session, principal, ticket_id, for_update=True)
    if ticket is None:
        raise TicketNotFoundError()
    if not can_manage(principal):
        raise ForbiddenError("You may view this ticket but not change it.")
    if ticket.status == "closed":
        raise TicketClosedError("A closed ticket can no longer be changed.")
    return ticket


def change_status(
    session: Session, principal: Principal, ticket_id: uuid.UUID, target: str, reason: str | None
) -> Ticket:
    ticket = _load_for_change(session, principal, ticket_id)
    previous = ticket.status
    check_transition(previous, target)
    now = _now()
    ticket.status = target
    if target == "resolved":
        ticket.resolved_at = now
    elif target == "open" and previous == "resolved":
        ticket.resolved_at = None
    if target == "closed":
        ticket.closed_at = now
        ticket.resolved_at = ticket.resolved_at or now
    _audit(
        session,
        principal,
        ticket,
        "ticket.status_changed",
        {"status": {"old": previous, "new": target}, "reason": reason},
    )
    _flush(session)
    return ticket


def assign(
    session: Session, principal: Principal, ticket_id: uuid.UUID, assignee_id: uuid.UUID
) -> Ticket:
    ticket = _load_for_change(session, principal, ticket_id)
    if not identity_api.is_assignable_support_user(session, ticket.tenant_id, assignee_id):
        raise InvalidAssigneeError(
            "Tickets can only be assigned to active support staff of your organisation."
        )
    previous = ticket.assignee_user_id
    if previous == assignee_id:
        raise ConflictError("The ticket is already assigned to this person.")
    ticket.assignee_user_id = assignee_id
    _audit(
        session,
        principal,
        ticket,
        "ticket.assigned",
        {"assignee_user_id": {"old": previous, "new": assignee_id}},
    )
    publish_event(
        session,
        ticket.tenant_id,
        "ticket.assigned",
        {
            "ticket_id": str(ticket.id),
            "assignee_id": str(assignee_id),
            "actor_id": str(principal.user_id) if principal.user_id else None,
        },
    )
    _flush(session)
    return ticket


def update_ticket(
    session: Session,
    principal: Principal,
    ticket_id: uuid.UUID,
    version: int,
    *,
    priority: str | None,
    category: str | None,
) -> Ticket:
    ticket = _load_for_change(session, principal, ticket_id)
    if ticket.version != version:
        raise VersionConflictError(
            f"The ticket was changed by someone else (now version {ticket.version}). Reload it."
        )
    if category is not None and category != ticket.category:
        _audit(
            session,
            principal,
            ticket,
            "ticket.category_changed",
            {"category": {"old": ticket.category, "new": category}},
        )
        ticket.category = category
    previous = ticket.priority
    if priority is not None and previous != priority:
        ticket.priority = priority
        # SLA targets follow the new priority, counted from when the ticket was opened.
        ticket.first_response_due_at, ticket.resolution_due_at = due_times(
            priority, ticket.created_at
        )
        _audit(
            session,
            principal,
            ticket,
            "ticket.priority_changed",
            {"priority": {"old": previous, "new": priority}},
        )
    _flush(session)
    return ticket


def add_staff_comment(
    session: Session, principal: Principal, ticket_id: uuid.UUID, body: str, visibility: str
) -> TicketComment:
    ticket = _load_for_change(session, principal, ticket_id)
    if visibility == "public":
        if ticket.first_responded_at is None:
            ticket.first_responded_at = _now()
        if ticket.status == "new":
            ticket.status = "open"
    comment = TicketComment(
        tenant_id=ticket.tenant_id,
        ticket_id=ticket.id,
        author_user_id=principal.user_id,
        body=body,
        visibility=visibility,
    )
    session.add(comment)
    ticket.updated_at = _now()
    _flush(session)
    return comment


# --- change (customer) --------------------------------------------------------------------


def add_customer_comment(
    session: Session, principal: Principal, ticket_id: uuid.UUID, body: str
) -> TicketComment:
    if principal.user_type != "customer" or not principal.has_permission(
        Permission.PORTAL_TICKET_WRITE
    ):
        raise ForbiddenError("Only customers can reply here.")
    ticket = repository.get_readable(session, principal, ticket_id, for_update=True)
    if ticket is None:
        raise TicketNotFoundError()
    if ticket.status == "closed":
        raise TicketClosedError("This ticket is closed. Please open a new ticket.")
    if ticket.status in ("pending_customer", "resolved"):
        # The customer answered or says it isn't fixed: back to the support team.
        _audit(
            session,
            principal,
            ticket,
            "ticket.status_changed",
            {"status": {"old": ticket.status, "new": "open"}, "reason": "Customer replied"},
        )
        ticket.status = "open"
        ticket.resolved_at = None
    comment = TicketComment(
        tenant_id=ticket.tenant_id,
        ticket_id=ticket.id,
        author_user_id=principal.user_id,
        body=body,
        visibility="public",
    )
    session.add(comment)
    ticket.updated_at = _now()
    publish_event(
        session, ticket.tenant_id, "ticket.customer_replied", {"ticket_id": str(ticket.id)}
    )
    _flush(session)
    return comment


class TicketNotResolvedError(ConflictError):
    code = "ticket_not_resolved"


class AlreadyRatedError(ConflictError):
    code = "already_rated"


def rate_ticket(
    session: Session,
    principal: Principal,
    ticket_id: uuid.UUID,
    *,
    rating: int,
    comment: str | None,
) -> Ticket:
    """The customer rates a resolved (or closed) ticket - once. Runs AS the customer."""
    if principal.user_type != "customer" or not principal.has_permission(
        Permission.PORTAL_TICKET_WRITE
    ):
        raise ForbiddenError("Only customers can rate their tickets.")
    ticket = repository.get_readable(session, principal, ticket_id, for_update=True)
    if ticket is None:
        raise TicketNotFoundError()
    if ticket.status not in ("resolved", "closed"):
        raise TicketNotResolvedError("You can rate a ticket once it has been resolved.")
    if ticket.satisfaction_rating is not None:
        raise AlreadyRatedError("This ticket has already been rated. Thank you!")
    ticket.satisfaction_rating = rating
    ticket.satisfaction_comment = comment or None
    ticket.rated_at = _now()
    _audit(session, principal, ticket, "ticket.rated", {"rating": rating})
    _flush(session)
    return ticket
