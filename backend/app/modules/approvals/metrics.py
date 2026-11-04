"""Figures about the proposals the Qualifier made (docs/pilot-report.md, step PR2b).

Aggregates only: counts and times, never a lead, a name or the text of a reason. Row-level security
limits it to the person's organisation; the reports module decides who may ask.
"""

from decimal import Decimal

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.reporting import Column, Filters, Table, percent
from app.modules.approvals.models import AgentAction

QUALIFIER = "qualifier"


def qualifier_suggestions_table(session: Session, principal: Principal, filters: Filters) -> Table:
    """Proposals the Qualifier made in the period, and what people did with them.

    *Approved share* = approved / (approved + rejected): only what a person decided. An expired or
    failed proposal says nothing about whether the suggestion was good, so it stays out of it.
    """
    period = filters.period
    minutes = func.extract("epoch", AgentAction.decided_at - AgentAction.created_at) / 60
    decided = AgentAction.status.in_(("approved", "rejected"))

    def count(status: str) -> ColumnElement[int]:
        return func.count().filter(AgentAction.status == status)

    proposed, approved, rejected, expired, failed, waiting, median = session.execute(
        select(
            func.count(),
            count("approved"),
            count("rejected"),
            count("expired"),
            count("failed"),
            count("pending"),
            func.percentile_cont(0.5).within_group(func.greatest(minutes, 0)).filter(decided),
        ).where(
            AgentAction.agent == QUALIFIER,
            AgentAction.created_at >= period.start,
            AgentAction.created_at < period.end,
        )
    ).one()
    return Table(
        "Qualifier suggestions and what people did with them",
        (
            Column("proposed", "Suggestions", "number"),
            Column("approved", "Approved", "number"),
            Column("rejected", "Rejected", "number"),
            Column("expired", "Expired", "number"),
            Column("failed", "Could not be carried out", "number"),
            Column("waiting", "Still waiting", "number"),
            Column("approved_share", "Approved of those decided %", "percent"),
            Column("median_minutes_to_decision", "Median minutes to a decision", "number"),
        ),
        [
            {
                "proposed": proposed,
                "approved": approved,
                "rejected": rejected,
                "expired": expired,
                "failed": failed,
                "waiting": waiting,
                "approved_share": percent(approved, approved + rejected),
                "median_minutes_to_decision": (
                    None if median is None else Decimal(str(median)).quantize(Decimal("0.1"))
                ),
            }
        ],
    )
