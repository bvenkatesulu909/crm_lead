"""Builds the dashboards from the other modules' figures.

Which view a user gets:
- executive       (``dashboard:executive``, tenant admins): sales + team + revenue, orders, support
- manager         (``dashboard:sales:all``, sales managers and admins): sales for everyone + team
- representative  (any dashboard permission): the user's OWN records only

Every figure comes from the module that owns the data, with that module's record-level policy,
so the numbers can never include records the user could not open. The "sales rep" filter is
only accepted in the manager and executive views, and only for staff of the user's own tenant.
"""

import uuid
from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.errors import DomainError, ForbiddenError
from app.core.reporting import ActivityItem, Filters, Money, Period
from app.modules.accounts import api as accounts_api
from app.modules.dashboard.schemas import (
    ActivityRead,
    CustomerFigures,
    DashboardRead,
    FollowUpFigures,
    FollowUpRead,
    LeadFigures,
    MoneyRead,
    OrderFigures,
    PeriodRead,
    PipelineFigures,
    RepFigures,
    RevenueFigures,
    StageRead,
    SupportFigures,
    View,
)
from app.modules.identity import api as identity_api
from app.modules.invoices import api as invoices_api
from app.modules.leads import api as leads_api
from app.modules.orders import api as orders_api
from app.modules.sales import api as sales_api
from app.modules.support import api as support_api

DEFAULT_DAYS = 30
MAX_DAYS = 3 * 366
ACTIVITY_LIMIT = 15


class InvalidFilterError(DomainError):
    status_code = 422
    code = "invalid_filter"


def available_views(principal: Principal) -> list[View]:
    views: list[View] = []
    if principal.has_permission(Permission.DASHBOARD_EXECUTIVE):
        views.append("executive")
    if principal.has_permission(Permission.DASHBOARD_SALES_ALL):
        views.append("manager")
    if views or principal.has_permission(Permission.DASHBOARD_SALES_OWN):
        views.append("representative")
    return views


def _period(start: date | None, end: date | None) -> Period:
    today = datetime.now(UTC).date()
    end = end or today
    start = start or end - timedelta(days=DEFAULT_DAYS - 1)
    if start > end:
        raise InvalidFilterError("The start date must be on or before the end date.")
    if (end - start).days > MAX_DAYS:
        raise InvalidFilterError("Choose a period of at most three years.")
    return Period(start, end)


def _money(values: list[Money]) -> list[MoneyRead]:
    return [MoneyRead(currency=m.currency, amount=m.amount) for m in values]


def _merge_activities(*lists: list[ActivityItem]) -> list[ActivityItem]:
    items = [item for items in lists for item in items]
    return sorted(items, key=lambda i: i.at, reverse=True)[:ACTIVITY_LIMIT]


def build_dashboard(
    session: Session,
    principal: Principal,
    *,
    view: View | None,
    start: date | None,
    end: date | None,
    owner_id: uuid.UUID | None,
) -> DashboardRead:
    if principal.user_type != "staff" or principal.tenant_id is None or principal.user_id is None:
        raise ForbiddenError("Dashboards are for staff of an organisation.")
    views = available_views(principal)
    if not views:
        raise ForbiddenError("Your role has no dashboard.")
    chosen: View = view or views[0]
    if chosen not in views:
        raise ForbiddenError("This dashboard is not part of your role.")
    if chosen == "representative":
        if owner_id is not None and owner_id != principal.user_id:
            raise ForbiddenError("The sales rep filter is only available to managers.")
        owner_id = principal.user_id
    elif owner_id is not None and not identity_api.staff_member_exists(
        session, principal.tenant_id, owner_id
    ):
        raise InvalidFilterError("Unknown sales rep.")
    filters = Filters(_period(start, end), owner_id)

    lead = leads_api.lead_metrics(session, principal, filters)
    customers = accounts_api.customer_metrics(session, principal, filters)
    pipeline = sales_api.pipeline_metrics(session, principal, filters)
    follow = leads_api.follow_ups(session, principal, filters)
    activities = _merge_activities(
        leads_api.recent_lead_activities(session, principal, filters, limit=ACTIVITY_LIMIT),
        support_api.recent_ticket_activities(session, principal, filters, limit=ACTIVITY_LIMIT),
        orders_api.recent_order_activities(session, principal, filters, limit=ACTIVITY_LIMIT),
    )
    people_ids = {f.owner_id for f in follow.oldest if f.owner_id} | {
        a.actor_user_id for a in activities if a.actor_user_id
    }
    people = identity_api.people_by_id(session, principal.tenant_id, people_ids)
    now = datetime.now(UTC)

    result = DashboardRead(
        view=chosen,
        available_views=views,
        period=PeriodRead(start=filters.period.start_date, end=filters.period.end_date),
        owner_id=owner_id if chosen != "representative" else None,
        leads=LeadFigures(
            created=lead.created,
            assigned=lead.assigned,
            unassigned=lead.created - lead.assigned,
            new=lead.by_status["new"],
            contacted=lead.by_status["contacted"],
            qualified=lead.by_status["qualified"],
            unqualified=lead.by_status["unqualified"],
            converted=lead.by_status["converted"],
            converted_in_period=lead.converted_in_period,
            open_now=lead.open_now,
            conversion_rate=round(lead.by_status["converted"] / lead.created, 4)
            if lead.created
            else None,
        ),
        customers=CustomerFigures(**asdict(customers)),
        pipeline=PipelineFigures(
            open_count=pipeline.open_count,
            open_value=_money(pipeline.open_value),
            by_stage=[
                StageRead(stage=s.stage, count=s.count, value=_money(s.value))
                for s in pipeline.by_stage
            ],
            closing_in_period=pipeline.closing_in_period,
            closing_in_period_value=_money(pipeline.closing_in_period_value),
            without_amount=pipeline.without_amount,
        ),
        follow_ups=FollowUpFigures(
            total=follow.total,
            rule="Open leads with no activity for 7 days or more",
            items=[
                FollowUpRead(
                    lead_id=f.lead_id,
                    name=f.name,
                    company=f.company,
                    status=f.status,
                    owner_name=people.get(f.owner_id, ("Former colleague", ""))[0]
                    if f.owner_id
                    else None,
                    last_touch_at=f.last_touch_at,
                    days_idle=(now - f.last_touch_at).days,
                )
                for f in follow.oldest
            ],
        ),
        recent_activities=[
            ActivityRead(
                at=a.at,
                kind=a.kind,
                title=a.title,
                detail=a.detail,
                record_type=a.record_type,
                record_id=a.record_id,
                actor_name=people.get(a.actor_user_id, ("Former user", ""))[0]
                if a.actor_user_id
                else None,
            )
            for a in activities
        ],
    )
    if chosen in ("manager", "executive"):
        result = result.model_copy(update={"team": _team(session, principal, filters)})
    if chosen == "executive":
        revenue = invoices_api.revenue_metrics(session, principal, filters)
        orders = orders_api.order_metrics(session, principal, filters)
        support = support_api.support_metrics(session, principal, filters)
        result = result.model_copy(
            update={
                "revenue": RevenueFigures(
                    issued_count=revenue.issued_count,
                    issued_value=_money(revenue.issued_value),
                    received=_money(revenue.received),
                    outstanding_count=revenue.outstanding_count,
                    outstanding=_money(revenue.outstanding),
                    overdue_count=revenue.overdue_count,
                    overdue=_money(revenue.overdue),
                ),
                "orders": OrderFigures(
                    confirmed_in_period=orders.confirmed_in_period,
                    confirmed_value=_money(orders.confirmed_value),
                    in_progress_now=orders.in_progress_now,
                ),
                "support": SupportFigures(**asdict(support)),
            }
        )
    return result


def _team(session: Session, principal: Principal, filters: Filters) -> list[RepFigures]:
    """One row per sales rep (and one for records without an owner, if any)."""
    if principal.tenant_id is None:  # checked by build_dashboard; keeps the type checker sure
        return []
    unfiltered = replace(filters, owner_id=None)
    leads = leads_api.lead_figures_by_owner(session, principal, unfiltered)
    customers = accounts_api.customers_by_owner(session, principal, unfiltered)
    pipeline = sales_api.open_pipeline_by_owner(session, principal, unfiltered)
    reps = identity_api.sales_people(session, principal.tenant_id)
    if filters.owner_id is not None:
        reps = [(i, n) for i, n in reps if i == filters.owner_id]
    rows: list[RepFigures] = []
    owners: list[tuple[uuid.UUID | None, str]] = list(reps)
    if filters.owner_id is None and (None in leads or None in pipeline):
        owners.append((None, "No owner"))
    for owner, name in owners:
        figures = leads.get(owner, leads_api.OwnerLeadFigures())
        opp_count, opp_value = pipeline.get(owner, (0, []))
        rows.append(
            RepFigures(
                user_id=owner,
                name=name,
                leads_created=figures.created,
                qualified=figures.qualified,
                converted_in_period=figures.converted_in_period,
                customers=customers.get(owner, 0),
                open_opportunities=opp_count,
                open_value=_money(opp_value),
                follow_ups=figures.follow_ups,
            )
        )
    return rows
