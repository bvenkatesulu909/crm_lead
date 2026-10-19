"""Database queries for tickets. Every query applies ``readable_tickets``."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, Select, and_, func, or_, select, text
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.search import escape_like
from app.modules.support.models import Ticket, TicketComment
from app.modules.support.policies import readable_tickets

_SORTS = {
    "created_at": Ticket.created_at,
    "updated_at": Ticket.updated_at,
    "resolution_due_at": Ticket.resolution_due_at,
}


@dataclass(frozen=True)
class TicketFilters:
    q: str | None = None
    statuses: tuple[str, ...] = ()
    priority: str | None = None
    category: str | None = None
    assignee_id: uuid.UUID | None = None
    unassigned: bool = False
    account_id: uuid.UUID | None = None
    overdue: bool = False
    sort: str = "-created_at"
    limit: int = 50
    offset: int = 0


def next_ticket_number(session: Session, tenant_id: uuid.UUID) -> int:
    """Atomically take the next number for this tenant (safe under concurrent requests)."""
    number = session.scalar(
        text(
            "INSERT INTO ticket_number_counters (tenant_id, last_number) VALUES (:t, 1) "
            "ON CONFLICT (tenant_id) DO UPDATE "
            "SET last_number = ticket_number_counters.last_number + 1 "
            "RETURNING last_number"
        ),
        {"t": tenant_id},
    )
    if number is None:
        raise RuntimeError("could not allocate a ticket number")
    return int(number)


def _filtered(principal: Principal, filters: TicketFilters, now: datetime) -> Select[Ticket]:
    statement = select(Ticket).where(readable_tickets(principal))
    if filters.q:
        term = filters.q.strip()
        digits = term.upper().removeprefix("T-").lstrip("0")
        conditions: list[ColumnElement[bool]] = [
            Ticket.subject.ilike(f"%{escape_like(term)}%", escape="\\")
        ]
        if digits.isdigit():
            conditions.append(Ticket.number == int(digits))
        statement = statement.where(or_(*conditions))
    if filters.statuses:
        statement = statement.where(Ticket.status.in_(filters.statuses))
    if filters.priority:
        statement = statement.where(Ticket.priority == filters.priority)
    if filters.category:
        statement = statement.where(Ticket.category == filters.category)
    if filters.assignee_id:
        statement = statement.where(Ticket.assignee_user_id == filters.assignee_id)
    if filters.unassigned:
        statement = statement.where(Ticket.assignee_user_id.is_(None))
    if filters.account_id:
        statement = statement.where(Ticket.account_id == filters.account_id)
    if filters.overdue:
        statement = statement.where(
            Ticket.status.notin_(("resolved", "closed")),
            or_(
                Ticket.resolution_due_at < now,
                and_(Ticket.first_responded_at.is_(None), Ticket.first_response_due_at < now),
            ),
        )
    return statement


def search(
    session: Session, principal: Principal, filters: TicketFilters, now: datetime
) -> tuple[Sequence[Ticket], int]:
    statement = _filtered(principal, filters, now)
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    column = _SORTS[filters.sort.lstrip("-")]
    order = column.desc() if filters.sort.startswith("-") else column.asc()
    page = statement.order_by(order, Ticket.id).limit(filters.limit).offset(filters.offset)
    return session.scalars(page).all(), total


def get_readable(
    session: Session, principal: Principal, ticket_id: uuid.UUID, *, for_update: bool = False
) -> Ticket | None:
    statement = select(Ticket).where(Ticket.id == ticket_id, readable_tickets(principal))
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return session.scalars(statement).one_or_none()


def comments(
    session: Session, ticket: Ticket, *, include_internal: bool
) -> Sequence[TicketComment]:
    statement = select(TicketComment).where(
        TicketComment.tenant_id == ticket.tenant_id, TicketComment.ticket_id == ticket.id
    )
    if not include_internal:
        statement = statement.where(TicketComment.visibility == "public")
    return session.scalars(statement.order_by(TicketComment.seq)).all()
