"""Database queries for opportunities. Every query goes through ``readable_opportunities``."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.search import escape_like
from app.modules.sales.models import Opportunity, OpportunityStageChange
from app.modules.sales.policies import readable_opportunities


@dataclass(frozen=True)
class OpportunityFilters:
    q: str | None = None
    account_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    stages: tuple[str, ...] = ()
    limit: int = 50
    offset: int = 0


def _filtered(principal: Principal, f: OpportunityFilters) -> Select[Opportunity]:
    statement = select(Opportunity).where(readable_opportunities(principal))
    if f.q:
        pattern = f"%{escape_like(f.q)}%"
        statement = statement.where(
            or_(
                Opportunity.name.ilike(pattern, escape="\\"),
                Opportunity.next_step.ilike(pattern, escape="\\"),
            )
        )
    if f.account_id:
        statement = statement.where(Opportunity.account_id == f.account_id)
    if f.owner_id:
        statement = statement.where(Opportunity.owner_id == f.owner_id)
    if f.stages:
        statement = statement.where(Opportunity.stage.in_(f.stages))
    return statement


def search(
    session: Session, principal: Principal, f: OpportunityFilters
) -> tuple[Sequence[Opportunity], int]:
    statement = _filtered(principal, f)
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    page = statement.order_by(Opportunity.created_at.desc(), Opportunity.id)
    return session.scalars(page.limit(f.limit).offset(f.offset)).all(), total


def column(
    session: Session,
    principal: Principal,
    f: OpportunityFilters,
    stage: str,
    *,
    closed_since: datetime | None,
    limit: int,
) -> tuple[Sequence[Opportunity], int, list[tuple[str, Decimal | None]]]:
    """One board column: up to ``limit`` cards (closing soonest first), how many there are in
    total, and (currency, summed amount) rows - counted in SQL, not from the shown cards."""
    statement = _filtered(principal, replace(f, stages=(stage,)))
    if closed_since is not None:
        statement = statement.where(Opportunity.closed_at >= closed_since)
    rows = statement.subquery()
    count = session.scalar(select(func.count()).select_from(rows)) or 0
    sums = session.execute(
        select(rows.c.currency, func.sum(rows.c.amount)).group_by(rows.c.currency)
    ).all()
    cards = session.scalars(
        statement.order_by(
            Opportunity.expected_close_date.asc().nulls_last(),
            func.lower(Opportunity.name),
            Opportunity.id,
        ).limit(limit)
    ).all()
    return cards, count, [(currency, total) for currency, total in sums]


def get_readable(
    session: Session, principal: Principal, opportunity_id: uuid.UUID, *, for_update: bool = False
) -> Opportunity | None:
    statement = select(Opportunity).where(
        Opportunity.id == opportunity_id, readable_opportunities(principal)
    )
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return session.scalars(statement).one_or_none()


def stage_changes(session: Session, opportunity: Opportunity) -> Sequence[OpportunityStageChange]:
    return session.scalars(
        select(OpportunityStageChange)
        .where(
            OpportunityStageChange.tenant_id == opportunity.tenant_id,
            OpportunityStageChange.opportunity_id == opportunity.id,
        )
        .order_by(OpportunityStageChange.changed_at.desc(), OpportunityStageChange.seq.desc())
    ).all()
