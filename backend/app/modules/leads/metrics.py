"""Lead figures for dashboards. Every query applies ``readable_leads`` (agents: own leads)."""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, and_, func, select
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.reporting import ActivityItem, Cell, Column, Filters, Table, percent
from app.modules.leads.models import USER_ACTIVITY_KINDS, Lead, LeadActivity
from app.modules.leads.policies import readable_leads

OPEN_STATUSES = ("new", "contacted", "qualified")
STALE_AFTER = timedelta(days=7)


@dataclass(frozen=True)
class LeadMetrics:
    created: int  # leads created in the period
    assigned: int  # ... of which have an owner
    by_status: dict[str, int]  # current status of the leads created in the period
    converted_in_period: int  # converted in the period, whenever they were created
    open_now: int  # new / contacted / qualified right now (not limited to the period)


@dataclass(frozen=True)
class FollowUp:
    lead_id: uuid.UUID
    name: str
    company: str | None
    status: str
    owner_id: uuid.UUID | None
    last_touch_at: datetime


@dataclass(frozen=True)
class FollowUps:
    total: int
    oldest: list[FollowUp] = field(default_factory=list)


@dataclass(frozen=True)
class OwnerLeadFigures:
    created: int = 0
    qualified: int = 0
    converted_in_period: int = 0
    follow_ups: int = 0


def _scope(principal: Principal, filters: Filters) -> ColumnElement[bool]:
    condition = readable_leads(principal)
    if filters.owner_id is not None:
        condition = and_(condition, Lead.owner_id == filters.owner_id)
    return condition


def lead_metrics(session: Session, principal: Principal, filters: Filters) -> LeadMetrics:
    scope = _scope(principal, filters)
    period = filters.period
    in_period = and_(Lead.created_at >= period.start, Lead.created_at < period.end)
    rows = session.execute(
        select(Lead.status, func.count(), func.count(Lead.owner_id))
        .where(scope, in_period)
        .group_by(Lead.status)
    ).all()
    by_status = {
        status: 0 for status in ("new", "contacted", "qualified", "unqualified", "converted")
    }
    created = assigned = 0
    for status, count, with_owner in rows:
        by_status[status] = count
        created += count
        assigned += with_owner
    converted = session.scalar(
        select(func.count()).where(
            scope, Lead.converted_at >= period.start, Lead.converted_at < period.end
        )
    )
    open_now = session.scalar(select(func.count()).where(scope, Lead.status.in_(OPEN_STATUSES)))
    return LeadMetrics(created, assigned, by_status, converted or 0, open_now or 0)


def _last_touch() -> ColumnElement[datetime]:
    """Latest activity on the lead (any kind), or its creation if it never had one."""
    latest = (
        select(func.max(LeadActivity.occurred_at))
        .where(LeadActivity.tenant_id == Lead.tenant_id, LeadActivity.lead_id == Lead.id)
        .scalar_subquery()
    )
    return func.coalesce(latest, Lead.created_at)


def follow_ups(
    session: Session, principal: Principal, filters: Filters, *, limit: int = 8
) -> FollowUps:
    """Open leads nobody has touched for 7 days or more - the real "to follow up" list until
    tasks and reminders exist (Phase 9)."""
    touch = _last_touch().label("last_touch")
    cutoff = datetime.now(UTC) - STALE_AFTER
    stale = select(Lead, touch).where(
        _scope(principal, filters), Lead.status.in_(OPEN_STATUSES), _last_touch() < cutoff
    )
    total = session.scalar(select(func.count()).select_from(stale.subquery())) or 0
    rows = session.execute(stale.order_by(touch.asc(), Lead.id).limit(limit)).all()
    return FollowUps(
        total,
        [
            FollowUp(
                lead.id,
                " ".join(p for p in (lead.first_name, lead.last_name) if p),
                lead.company_name,
                lead.status,
                lead.owner_id,
                last_touch,
            )
            for lead, last_touch in rows
        ],
    )


def lead_figures_by_owner(
    session: Session, principal: Principal, filters: Filters
) -> dict[uuid.UUID | None, OwnerLeadFigures]:
    scope = _scope(principal, filters)
    period = filters.period
    figures: dict[uuid.UUID | None, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for owner, status, count in session.execute(
        select(Lead.owner_id, Lead.status, func.count())
        .where(scope, Lead.created_at >= period.start, Lead.created_at < period.end)
        .group_by(Lead.owner_id, Lead.status)
    ).all():
        figures[owner]["created"] += count
        if status == "qualified":
            figures[owner]["qualified"] += count
    for owner, count in session.execute(
        select(Lead.owner_id, func.count())
        .where(scope, Lead.converted_at >= period.start, Lead.converted_at < period.end)
        .group_by(Lead.owner_id)
    ).all():
        figures[owner]["converted_in_period"] += count
    cutoff = datetime.now(UTC) - STALE_AFTER
    for owner, count in session.execute(
        select(Lead.owner_id, func.count())
        .where(scope, Lead.status.in_(OPEN_STATUSES), _last_touch() < cutoff)
        .group_by(Lead.owner_id)
    ).all():
        figures[owner]["follow_ups"] += count
    return {owner: OwnerLeadFigures(**values) for owner, values in figures.items()}


_TITLES = {
    "note": "Note",
    "call": "Call",
    "email": "E-mail",
    "meeting": "Meeting",
    "created": "Lead created",
    "status_changed": "Status changed",
    "assigned": "Lead assigned",
    "converted": "Lead converted to customer",
}


def recent_lead_activities(
    session: Session, principal: Principal, filters: Filters, *, limit: int = 15
) -> list[ActivityItem]:
    period = filters.period
    rows = session.execute(
        select(LeadActivity, Lead)
        .join(Lead, and_(Lead.tenant_id == LeadActivity.tenant_id, Lead.id == LeadActivity.lead_id))
        .where(
            _scope(principal, filters),
            LeadActivity.occurred_at >= period.start,
            LeadActivity.occurred_at < period.end,
        )
        .order_by(LeadActivity.occurred_at.desc(), LeadActivity.seq.desc())
        .limit(limit)
    ).all()
    items = []
    for activity, lead in rows:
        name = " ".join(p for p in (lead.first_name, lead.last_name) if p)
        manual = activity.kind in USER_ACTIVITY_KINDS
        items.append(
            ActivityItem(
                at=activity.occurred_at,
                kind=f"lead.{activity.kind}",
                title=f"{_TITLES.get(activity.kind, activity.kind)}: {name}",
                detail=activity.subject if manual else (lead.company_name or None),
                record_type="lead",
                record_id=lead.id,
                actor_user_id=activity.actor_user_id,
            )
        )
    return items


def conversion_table(session: Session, principal: Principal, filters: Filters) -> Table:
    """Leads created in the period by source: how many converted, were dropped or are open."""
    period = filters.period
    rows = session.execute(
        select(
            Lead.source,
            func.count(),
            func.count().filter(Lead.status == "converted"),
            func.count().filter(Lead.status == "unqualified"),
        )
        .where(
            _scope(principal, filters),
            Lead.created_at >= period.start,
            Lead.created_at < period.end,
        )
        .group_by(Lead.source)
    ).all()
    out: list[dict[str, Cell]] = []
    totals = [0, 0, 0]
    for source, created, converted, dropped in sorted(rows, key=lambda r: -int(r[1])):
        out.append(
            {
                "source": source or "(none)",
                "created": created,
                "converted": converted,
                "unqualified": dropped,
                "open": created - converted - dropped,
                "conversion_rate": percent(converted, created),
            }
        )
        totals = [totals[0] + created, totals[1] + converted, totals[2] + dropped]
    if out:
        created, converted, dropped = totals
        out.append(
            {
                "source": "Total",
                "created": created,
                "converted": converted,
                "unqualified": dropped,
                "open": created - converted - dropped,
                "conversion_rate": percent(converted, created),
            }
        )
    return Table(
        "Lead conversion by source",
        (
            Column("source", "Source"),
            Column("created", "Created", "number"),
            Column("converted", "Converted", "number"),
            Column("unqualified", "Unqualified", "number"),
            Column("open", "Still open", "number"),
            Column("conversion_rate", "Conversion %", "percent"),
        ),
        out,
    )
