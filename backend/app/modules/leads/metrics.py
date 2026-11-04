"""Lead figures for dashboards. Every query applies ``readable_leads`` (agents: own leads)."""

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
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


def created_at_of(
    session: Session, principal: Principal, lead_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, datetime]:
    """When each of these leads was created - only the leads this person may read."""
    if not lead_ids:
        return {}
    rows = session.execute(
        select(Lead.id, Lead.created_at).where(readable_leads(principal), Lead.id.in_(lead_ids))
    ).all()
    return {lead_id: created for lead_id, created in rows}


def web_lead_quality_table(session: Session, principal: Principal, filters: Filters) -> Table:
    """Leads that came from the website chat in the period: how many arrived with their details,
    and how long until someone first reached out (docs/pilot-report.md). Aggregates only.

    *Details*: a budget (either end), an area and a property type. *First call*: the earlier of the
    first logged call and the first change of status to "contacted" (from the audit trail, where the
    change is stored in structured form). A call logged before the lead existed counts as no wait.
    """
    period = filters.period
    call_at = (
        select(func.min(LeadActivity.occurred_at))
        .where(LeadActivity.lead_id == Lead.id, LeadActivity.kind == "call")
        .scalar_subquery()
    )
    contacted_at = (
        select(func.min(AuditLog.occurred_at))
        .where(
            AuditLog.entity_type == "lead",
            AuditLog.entity_id == Lead.id,
            AuditLog.action == "lead.status_changed",
            AuditLog.changes["status"]["new"].astext == "contacted",
        )
        .scalar_subquery()
    )
    first_contact = func.least(call_at, contacted_at)  # LEAST ignores a missing one
    wait_hours = func.greatest(func.extract("epoch", first_contact - Lead.created_at), 0) / 3600
    has_details = and_(
        or_(Lead.budget_min_inr.is_not(None), Lead.budget_max_inr.is_not(None)),
        func.length(func.trim(func.coalesce(Lead.location, ""))) > 0,
        Lead.property_type.is_not(None),
    )
    total, detailed, called, median = session.execute(
        select(
            func.count(),
            func.count().filter(has_details),
            func.count().filter(first_contact.is_not(None)),
            func.percentile_cont(0.5).within_group(wait_hours).filter(first_contact.is_not(None)),
        ).where(
            _scope(principal, filters),
            Lead.source == "web",
            Lead.created_at >= period.start,
            Lead.created_at < period.end,
        )
    ).one()
    return Table(
        "Web leads: details and time to the first call",
        (
            Column("web_leads", "Web leads", "number"),
            Column("with_details", "With budget, area and type", "number"),
            Column("with_details_share", "With details %", "percent"),
            Column("called", "Reached out to", "number"),
            Column("median_hours_to_first_call", "Median hours to the first call", "number"),
        ),
        [
            {
                "web_leads": total,
                "with_details": detailed,
                "with_details_share": percent(detailed, total),
                "called": called,
                "median_hours_to_first_call": (
                    None if median is None else Decimal(str(median)).quantize(Decimal("0.1"))
                ),
            }
        ],
    )


def web_leads_by_month(
    session: Session, principal: Principal, months: Sequence[date]
) -> dict[date, int]:
    """Web leads created in each whole UTC calendar month (``months`` are first days), under the
    leads module's own record policy. Months without a lead are present with 0."""
    if not months:
        return {}
    first = min(months)
    last = max(months)
    end = datetime(last.year + (last.month == 12), last.month % 12 + 1, 1, tzinfo=UTC)
    month = func.date_trunc("month", func.timezone("UTC", Lead.created_at))
    rows = session.execute(
        select(month, func.count())
        .where(
            readable_leads(principal),
            Lead.source == "web",
            Lead.created_at >= datetime(first.year, first.month, 1, tzinfo=UTC),
            Lead.created_at < end,
        )
        .group_by(month)
    ).all()
    found = {m.date(): n for m, n in rows}
    return {m: found.get(m, 0) for m in months}
