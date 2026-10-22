"""Public interface of the support module.

``create_customer_ticket`` is the HUMAN HANDOFF the AI assistant will use: when it cannot
safely help, it opens a ticket with ``channel="assistant"`` and a summary of the conversation.
It runs as the signed-in customer, so the same rules apply as in the portal: only the
customer's own granted accounts, nothing in another tenant. The caller commits.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.errors import ForbiddenError
from app.core.records import RecordFacts
from app.core.reporting import Cell, Column, ExportFilters, ExportSpec, export_rows
from app.modules.support import repository, service
from app.modules.support.metrics import (
    SupportMetrics,
    recent_ticket_activities,
    sla_table,
    support_metrics,
)
from app.modules.support.models import TICKET_CATEGORIES as models_TICKET_CATEGORIES
from app.modules.support.models import TICKET_PRIORITIES as models_TICKET_PRIORITIES
from app.modules.support.models import TICKET_STATUSES, Ticket
from app.modules.support.policies import readable_tickets
from app.modules.support.repository import TicketFilters
from app.modules.support.schemas import PortalTicketRead
from app.modules.support.service import create_customer_ticket

__all__ = [
    "sla_table",
    "EXPORT",
    "export_table",
    "ticket_facts",
    "ticket_facts_by_reference",
    "TICKET_PRIORITIES",
    "TICKET_CATEGORIES",
    "ticket_assignee",
    "ticket_brief",
    "TicketSignals",
    "ticket_signals_by_account",
    "PortalTicketRead",
    "SupportMetrics",
    "create_customer_ticket",
    "customer_tickets",
    "recent_ticket_activities",
    "support_metrics",
]


def customer_tickets(
    session: Session,
    principal: Principal,
    *,
    q: str | None = None,
    account_id: uuid.UUID | None = None,
    limit: int = 20,
) -> list[PortalTicketRead]:
    """The customer's own tickets, as the portal shows them (for the AI assistant).

    Runs AS the customer: only tickets of their granted accounts, never internal notes."""
    if principal.user_type != "customer" or not principal.has_permission(
        Permission.PORTAL_TICKET_READ
    ):
        raise ForbiddenError("Only customers can use the portal ticket view.")
    items, _ = service.list_tickets(
        session, principal, TicketFilters(q=q, account_id=account_id, limit=limit)
    )
    return [service.to_portal_view(t) for t in items]


@dataclass(frozen=True)
class TicketSignals:
    open: int = 0
    sla_overdue: int = 0
    open_complaints: int = 0
    average_rating: float | None = None  # last 365 days
    ratings: int = 0
    last_ticket_at: datetime | None = None


def ticket_signals_by_account(
    session: Session, tenant_id: uuid.UUID, account_ids: list[uuid.UUID]
) -> dict[uuid.UUID, TicketSignals]:
    """Support figures per account for the customer-health indicator (counts only)."""
    if not account_ids:
        return {}
    now = datetime.now(UTC)
    is_open = Ticket.status.notin_(("resolved", "closed"))
    late = or_(
        Ticket.resolution_due_at < now,
        and_(Ticket.first_responded_at.is_(None), Ticket.first_response_due_at < now),
    )
    recent_rating = and_(
        Ticket.satisfaction_rating.is_not(None), Ticket.rated_at >= now - timedelta(days=365)
    )
    rows = session.execute(
        select(
            Ticket.account_id,
            func.count().filter(is_open),
            func.count().filter(and_(is_open, late)),
            func.count().filter(and_(is_open, Ticket.category == "complaint")),
            func.avg(Ticket.satisfaction_rating).filter(recent_rating),
            func.count().filter(recent_rating),
            func.max(Ticket.created_at),
        )
        .where(Ticket.tenant_id == tenant_id, Ticket.account_id.in_(account_ids))
        .group_by(Ticket.account_id)
    ).all()
    return {
        account: TicketSignals(
            open=n_open,
            sla_overdue=n_late,
            open_complaints=n_complaints,
            average_rating=round(float(avg), 2) if avg is not None else None,
            ratings=n_ratings,
            last_ticket_at=last,
        )
        for account, n_open, n_late, n_complaints, avg, n_ratings, last in rows
    }


def ticket_brief(
    session: Session, principal: Principal, ticket_id: uuid.UUID
) -> tuple[str, uuid.UUID | None] | None:
    """("T-0001: subject", assignee) for a ticket this principal may see, else None."""
    ticket = repository.get_readable(session, principal, ticket_id)
    if ticket is None:
        return None
    return f"T-{ticket.number:04d}: {ticket.subject}", ticket.assignee_user_id


def ticket_assignee(
    session: Session, tenant_id: uuid.UUID, ticket_id: uuid.UUID
) -> uuid.UUID | None:
    """Who works on a ticket, for notifications (each person is still checked with ticket_brief)."""
    return session.scalar(
        select(Ticket.assignee_user_id).where(Ticket.tenant_id == tenant_id, Ticket.id == ticket_id)
    )


TICKET_PRIORITIES = models_TICKET_PRIORITIES
TICKET_CATEGORIES = models_TICKET_CATEGORIES


def search_tickets(
    session: Session, principal: Principal, *, q: str, limit: int = 20
) -> list[dict[str, Any]]:
    items, _ = service.list_tickets(
        session, principal, TicketFilters(q=q.strip()[:100], limit=min(limit, 50))
    )
    return [
        {
            "id": str(t.id),
            "number": f"T-{t.number:04d}",
            "subject": t.subject,
            "status": t.status,
            "priority": t.priority,
            "link": f"/tickets/{t.id}",
        }
        for t in items
    ]


def ticket_facts_by_reference(
    session: Session, principal: Principal, reference: str
) -> RecordFacts | None:
    """Resolve a ticket number like T-0060 / 60 for this staff principal."""
    reference = reference.strip()
    try:
        return ticket_facts(session, principal, uuid.UUID(reference))
    except ValueError:
        pass
    raw = reference.upper().removeprefix("T-").lstrip("0") or "0"
    try:
        number = int(raw)
    except ValueError:
        return None
    items, _ = service.list_tickets(
        session, principal, TicketFilters(q=f"T-{number:04d}", limit=10)
    )
    for ticket in items:
        if ticket.number == number:
            return ticket_facts(session, principal, ticket.id)
    return None


def ticket_facts(
    session: Session, principal: Principal, ticket_id: uuid.UUID
) -> RecordFacts | None:
    ticket = repository.get_readable(session, principal, ticket_id)
    if ticket is None:
        return None
    return RecordFacts(
        record_type="ticket",
        record_id=ticket.id,
        label=f"T-{ticket.number:04d}: {ticket.subject}",
        link=f"/tickets/{ticket.id}",
        owner_id=ticket.assignee_user_id,
        account_id=ticket.account_id,
        lead_id=None,
        values={"priority": ticket.priority, "category": ticket.category, "status": ticket.status},
    )


# Report builder (Phase 18): the columns that may be exported - never internal notes - and the
# statuses to filter by. Rows always pass through this module's own record-level policy.
EXPORT = ExportSpec(
    columns=(
        Column("created_at", "Created", "datetime"),
        Column("number", "Ticket no.", "number"),
        Column("subject", "Subject", "text"),
        Column("account_id", "Account", "account"),
        Column("priority", "Priority", "text"),
        Column("category", "Category", "text"),
        Column("status", "Status", "text"),
        Column("resolved_at", "Resolved", "datetime"),
        Column("satisfaction_rating", "Rating", "number"),
        Column("assignee_user_id", "Assignee", "user"),
    ),
    statuses=TICKET_STATUSES,
)


def export_table(
    session: Session, principal: Principal, filters: ExportFilters, wanted: list[str]
) -> list[dict[str, Cell]]:
    allowed = {c.key for c in EXPORT.columns}
    if not wanted or not set(wanted) <= allowed:
        raise ValueError("unknown export column")
    return export_rows(
        session,
        entity=Ticket,
        columns={key: getattr(Ticket, key) for key in allowed},
        wanted=wanted,
        condition=readable_tickets(principal),
        created=Ticket.created_at,
        owner=Ticket.assignee_user_id,
        status=Ticket.status,
        filters=filters,
    )
