"""Support figures and activity for dashboards. Applies ``readable_tickets``."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.reporting import ActivityItem, Cell, Column, Filters, Table, percent
from app.modules.accounts import api as accounts_api
from app.modules.support.models import Ticket
from app.modules.support.policies import readable_tickets

CLOSED = ("resolved", "closed")


@dataclass(frozen=True)
class SupportMetrics:
    open_now: int
    sla_overdue_now: int
    opened_in_period: int
    complaints_in_period: int = 0  # tickets of category "complaint" opened in the period
    ratings_in_period: int = 0
    average_rating: float | None = None  # 1-5, ratings given in the period


def _scope(principal: Principal, filters: Filters) -> ColumnElement[bool]:
    condition = readable_tickets(principal)
    if filters.owner_id is not None and principal.tenant_id is not None:
        condition = and_(
            condition,
            Ticket.account_id.in_(
                accounts_api.accounts_owned_by(principal.tenant_id, filters.owner_id)
            ),
        )
    return condition


def support_metrics(session: Session, principal: Principal, filters: Filters) -> SupportMetrics:
    scope = _scope(principal, filters)
    now = datetime.now(UTC)
    is_open = Ticket.status.notin_(CLOSED)
    overdue = or_(
        Ticket.resolution_due_at < now,
        and_(Ticket.first_responded_at.is_(None), Ticket.first_response_due_at < now),
    )
    open_now, overdue_now = session.execute(
        select(func.count(), func.count().filter(overdue)).where(scope, is_open)
    ).one()
    period = filters.period
    opened = session.scalar(
        select(func.count()).where(
            scope, Ticket.created_at >= period.start, Ticket.created_at < period.end
        )
    )
    complaints = session.scalar(
        select(func.count()).where(
            scope,
            Ticket.category == "complaint",
            Ticket.created_at >= period.start,
            Ticket.created_at < period.end,
        )
    )
    ratings, average = session.execute(
        select(func.count(Ticket.satisfaction_rating), func.avg(Ticket.satisfaction_rating)).where(
            scope, Ticket.rated_at >= period.start, Ticket.rated_at < period.end
        )
    ).one()
    return SupportMetrics(
        open_now,
        overdue_now,
        opened or 0,
        complaints_in_period=complaints or 0,
        ratings_in_period=ratings,
        average_rating=round(float(average), 2) if average is not None else None,
    )


def recent_ticket_activities(
    session: Session, principal: Principal, filters: Filters, *, limit: int = 15
) -> list[ActivityItem]:
    period = filters.period
    tickets = session.scalars(
        select(Ticket)
        .where(
            _scope(principal, filters),
            Ticket.created_at >= period.start,
            Ticket.created_at < period.end,
        )
        .order_by(Ticket.created_at.desc(), Ticket.id)
        .limit(limit)
    ).all()
    return [
        ActivityItem(
            at=t.created_at,
            kind="ticket.opened",
            title=f"Support ticket opened: T-{t.number:04d}",
            detail=t.subject,
            record_type="ticket",
            record_id=t.id,
            actor_user_id=t.requester_user_id,
        )
        for t in tickets
    ]


def _one_decimal(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value)).quantize(Decimal("0.1"))


def sla_table(session: Session, principal: Principal, filters: Filters, *, by: str) -> Table:
    """Tickets per priority or category: created and resolved in the period, resolved late,
    open past their due time now, average hours to resolve and average rating (1-5)."""
    group = Ticket.priority if by == "priority" else Ticket.category
    period = filters.period
    now = datetime.now(UTC)
    created = and_(Ticket.created_at >= period.start, Ticket.created_at < period.end)
    resolved = and_(Ticket.resolved_at >= period.start, Ticket.resolved_at < period.end)
    hours = func.extract("epoch", Ticket.resolved_at - Ticket.created_at) / 3600
    rows = session.execute(
        select(
            group,
            func.count().filter(created),
            func.count().filter(resolved),
            func.count().filter(resolved, Ticket.resolved_at > Ticket.resolution_due_at),
            func.count().filter(
                Ticket.status.in_(("new", "open", "pending_customer")),
                Ticket.resolution_due_at < now,
            ),
            func.avg(hours).filter(resolved),
            func.avg(Ticket.satisfaction_rating).filter(resolved),
        )
        .where(_scope(principal, filters))
        .group_by(group)
        .order_by(group)
    ).all()
    out: list[dict[str, Cell]] = []
    for key, n_created, n_resolved, late, overdue, avg_hours, rating in rows:
        if not (n_created or n_resolved or overdue):
            continue
        out.append(
            {
                by: key,
                "created": n_created,
                "resolved": n_resolved,
                "resolved_late": late,
                "on_time_rate": percent(n_resolved - late, n_resolved),
                "overdue_now": overdue,
                "avg_hours": _one_decimal(avg_hours),
                "avg_rating": _one_decimal(rating),
            }
        )
    return Table(
        f"Support by {by}",
        (
            Column(by, by.capitalize()),
            Column("created", "Created", "number"),
            Column("resolved", "Resolved", "number"),
            Column("resolved_late", "Resolved late", "number"),
            Column("on_time_rate", "On time %", "percent"),
            Column("overdue_now", "Overdue now", "number"),
            Column("avg_hours", "Avg. hours to resolve", "number"),
            Column("avg_rating", "Avg. rating (1-5)", "number"),
        ),
        out,
    )
