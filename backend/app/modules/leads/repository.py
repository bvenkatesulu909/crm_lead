"""Database queries for leads. Every lead query goes through ``readable_leads``."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.search import escape_like
from app.modules.leads import scoring
from app.modules.leads.models import USER_ACTIVITY_KINDS, Lead, LeadActivity, LeadAssignment
from app.modules.leads.policies import readable_leads

_SORTS = {
    "created_at": Lead.created_at,
    "updated_at": Lead.updated_at,
    "last_name": Lead.last_name,
    "company_name": Lead.company_name,
}


@dataclass(frozen=True)
class LeadFilters:
    q: str | None = None
    statuses: tuple[str, ...] = ()
    owner_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    source: str | None = None
    priority: str | None = None  # hot / warm / cold (lead score bands)
    created_from: datetime | None = None
    created_to: datetime | None = None
    sort: str = "-created_at"
    limit: int = 50
    offset: int = 0


def _filtered(principal: Principal, filters: LeadFilters) -> Select[Lead]:
    statement = select(Lead).where(readable_leads(principal))
    if filters.q:
        pattern = f"%{escape_like(filters.q)}%"
        statement = statement.where(
            or_(
                Lead.first_name.ilike(pattern, escape="\\"),
                Lead.last_name.ilike(pattern, escape="\\"),
                Lead.company_name.ilike(pattern, escape="\\"),
                Lead.email.ilike(pattern, escape="\\"),
            )
        )
    if filters.statuses:
        statement = statement.where(Lead.status.in_(filters.statuses))
    if filters.owner_id:
        statement = statement.where(Lead.owner_id == filters.owner_id)
    if filters.account_id:
        statement = statement.where(Lead.converted_account_id == filters.account_id)
    if filters.source:
        statement = statement.where(Lead.source == filters.source)
    if filters.priority:
        statement = statement.where(scoring.priority_condition(filters.priority))
    if filters.created_from:
        statement = statement.where(Lead.created_at >= filters.created_from)
    if filters.created_to:
        statement = statement.where(Lead.created_at < filters.created_to)
    return statement


def search(
    session: Session, principal: Principal, filters: LeadFilters
) -> tuple[Sequence[Lead], int]:
    statement = _filtered(principal, filters)
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    key = filters.sort.lstrip("-")
    column = scoring.score_sql() if key == "score" else _SORTS[key]
    order = column.desc() if filters.sort.startswith("-") else column.asc()
    page = statement.order_by(order, Lead.id).limit(filters.limit).offset(filters.offset)
    return session.scalars(page).all(), total


def get_readable(
    session: Session, principal: Principal, lead_id: uuid.UUID, *, for_update: bool = False
) -> Lead | None:
    """The lead, or None if it does not exist OR the principal may not see it.

    ``for_update`` locks the row until the transaction ends, so two requests changing the same
    lead (e.g. two simultaneous conversions) run one after the other, never interleaved.
    """
    statement = select(Lead).where(Lead.id == lead_id, readable_leads(principal))
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return session.scalars(statement).one_or_none()


def list_activities(session: Session, lead: Lead) -> Sequence[LeadActivity]:
    return session.scalars(
        select(LeadActivity)
        .where(LeadActivity.tenant_id == lead.tenant_id, LeadActivity.lead_id == lead.id)
        .order_by(LeadActivity.occurred_at.desc(), LeadActivity.seq.desc())
    ).all()


def list_assignments(session: Session, lead: Lead) -> Sequence[LeadAssignment]:
    return session.scalars(
        select(LeadAssignment)
        .where(LeadAssignment.tenant_id == lead.tenant_id, LeadAssignment.lead_id == lead.id)
        .order_by(LeadAssignment.assigned_at.desc(), LeadAssignment.seq.desc())
    ).all()


def scores(
    session: Session, principal: Principal, lead_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Score of each given lead the principal may see (one query for a whole page)."""
    if not lead_ids:
        return {}
    rows = session.execute(
        select(Lead.id, scoring.score_sql()).where(Lead.id.in_(lead_ids), readable_leads(principal))
    ).all()
    return {lead_id: score for lead_id, score in rows}


def activity_stats(session: Session, lead: Lead) -> tuple[int, datetime | None]:
    """How many calls/e-mails/meetings/notes a lead has, and the latest one."""
    count, last = session.execute(
        select(func.count(), func.max(LeadActivity.occurred_at)).where(
            LeadActivity.tenant_id == lead.tenant_id,
            LeadActivity.lead_id == lead.id,
            LeadActivity.kind.in_(USER_ACTIVITY_KINDS),
        )
    ).one()
    return count, last
