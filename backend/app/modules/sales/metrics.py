"""Pipeline figures for dashboards. Applies ``readable_opportunities``.

Amounts are summed per currency - different currencies are never added together.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import ColumnElement, and_, func, select
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.reporting import Cell, Column, Filters, Money, Table, money_by_currency, percent
from app.modules.sales.models import OPPORTUNITY_STAGES, Opportunity
from app.modules.sales.policies import readable_opportunities

CLOSED_STAGES = ("closed_won", "closed_lost")
OPEN_STAGES = tuple(s for s in OPPORTUNITY_STAGES if s not in CLOSED_STAGES)


@dataclass(frozen=True)
class StageFigures:
    stage: str
    count: int
    value: list[Money]


@dataclass(frozen=True)
class PipelineMetrics:
    open_count: int  # open opportunities now
    open_value: list[Money]  # their total amount, per currency
    by_stage: list[StageFigures]  # open stages, in pipeline order
    closing_in_period: int  # open, expected close date inside the period
    closing_in_period_value: list[Money]
    without_amount: int  # open opportunities that have no amount yet


def _scope(principal: Principal, filters: Filters) -> ColumnElement[bool]:
    condition = readable_opportunities(principal)
    if filters.owner_id is not None:
        condition = and_(condition, Opportunity.owner_id == filters.owner_id)
    return condition


def pipeline_metrics(session: Session, principal: Principal, filters: Filters) -> PipelineMetrics:
    scope = and_(_scope(principal, filters), Opportunity.stage.in_(OPEN_STAGES))
    rows = session.execute(
        select(
            Opportunity.stage,
            Opportunity.currency,
            func.count(),
            func.sum(Opportunity.amount),
            func.count().filter(Opportunity.amount.is_(None)),
        )
        .where(scope)
        .group_by(Opportunity.stage, Opportunity.currency)
    ).all()
    stage_counts: dict[str, int] = defaultdict(int)
    stage_values: dict[str, list[tuple[str, Decimal | None]]] = defaultdict(list)
    without_amount = 0
    for stage, currency, count, total, missing in rows:
        stage_counts[stage] += count
        stage_values[stage].append((currency, total))
        without_amount += missing
    by_stage = [
        StageFigures(
            stage, stage_counts.get(stage, 0), money_by_currency(stage_values.get(stage, []))
        )
        for stage in OPEN_STAGES
    ]
    period = filters.period
    closing = session.execute(
        select(Opportunity.currency, func.count(), func.sum(Opportunity.amount))
        .where(
            scope,
            Opportunity.expected_close_date >= period.start_date,
            Opportunity.expected_close_date <= period.end_date,
        )
        .group_by(Opportunity.currency)
    ).all()
    return PipelineMetrics(
        open_count=sum(stage_counts.values()),
        open_value=money_by_currency((c, v) for _, c, _, v, _ in rows),
        by_stage=by_stage,
        closing_in_period=sum(count for _, count, _ in closing),
        closing_in_period_value=money_by_currency((c, v) for c, _, v in closing),
        without_amount=without_amount,
    )


def open_pipeline_by_owner(
    session: Session, principal: Principal, filters: Filters
) -> dict[uuid.UUID | None, tuple[int, list[Money]]]:
    grouped: dict[uuid.UUID | None, list[tuple[str, Decimal | None]]] = defaultdict(list)
    counts: dict[uuid.UUID | None, int] = defaultdict(int)
    for owner, currency, count, total in session.execute(
        select(
            Opportunity.owner_id, Opportunity.currency, func.count(), func.sum(Opportunity.amount)
        )
        .where(_scope(principal, filters), Opportunity.stage.in_(OPEN_STAGES))
        .group_by(Opportunity.owner_id, Opportunity.currency)
    ).all():
        counts[owner] += count
        grouped[owner].append((currency, total))
    return {owner: (counts[owner], money_by_currency(grouped[owner])) for owner in counts}


def win_loss_table(session: Session, principal: Principal, filters: Filters) -> Table:
    """Deals closed in the period, per sales rep and currency: won, lost, win rate, values."""
    period = filters.period
    rows = session.execute(
        select(
            Opportunity.owner_id,
            Opportunity.currency,
            func.count().filter(Opportunity.stage == "closed_won"),
            func.count().filter(Opportunity.stage == "closed_lost"),
            func.sum(Opportunity.amount).filter(Opportunity.stage == "closed_won"),
        )
        .where(
            _scope(principal, filters),
            Opportunity.stage.in_(CLOSED_STAGES),
            Opportunity.closed_at >= period.start,
            Opportunity.closed_at < period.end,
        )
        .group_by(Opportunity.owner_id, Opportunity.currency)
    ).all()
    out: list[dict[str, Cell]] = []
    for owner, currency, won, lost, won_value in sorted(rows, key=lambda r: (-int(r[2]), r[1])):
        value = won_value or Decimal("0.00")
        out.append(
            {
                "owner_id": owner,
                "currency": currency,
                "won": won,
                "lost": lost,
                "win_rate": percent(won, won + lost),
                "won_value": value,
                "average_won": (value / won).quantize(Decimal("0.01")) if won else None,
            }
        )
    return Table(
        "Deals won and lost",
        (
            Column("owner_id", "Sales rep", "user"),
            Column("won", "Won", "number"),
            Column("lost", "Lost", "number"),
            Column("win_rate", "Win rate %", "percent"),
            Column("won_value", "Won value", "money"),
            Column("average_won", "Average won deal", "money"),
            Column("currency", "Currency"),
        ),
        out,
    )
