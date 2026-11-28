"""Figures about the proposals the Qualifier made (docs/pilot-report.md, step PR2b).

Aggregates only: counts and times, never a lead, a name or the text of a reason. Row-level security
limits it to the person's organisation; the reports module decides who may ask.
"""

import uuid
from datetime import datetime
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


# --- automatic follow-up drafts (ADR 0036, step FM7) ----------------------------------------

FOLLOW_UP = "follow_up"
RULE_LABELS = {"task_due_today": "Follow-up task due today"}


def _follow_up_period(principal: Principal, filters: Filters) -> list[ColumnElement[bool]]:
    period = filters.period
    return [
        AgentAction.tenant_id == principal.tenant_id,  # row-level security says the same
        AgentAction.agent == FOLLOW_UP,
        AgentAction.created_at >= period.start,
        AgentAction.created_at < period.end,
    ]


def follow_up_drafts_table(session: Session, principal: Principal, filters: Filters) -> Table:
    """Follow-up drafts made in the period, per rule, and what people did with them.

    *Approved share* = approved / (approved + rejected), as for the Qualifier. *Reworded* counts
    approved drafts whose text the approver changed first (the proposal records THAT it was
    edited, never the text). Counts only: no lead, name, address or text.
    """
    rule = AgentAction.payload["reason_code"].astext
    edited = AgentAction.verification.has_key("edited")  # noqa: W601 - a JSONB operator
    minutes = func.extract("epoch", AgentAction.decided_at - AgentAction.created_at) / 60
    decided = AgentAction.status.in_(("approved", "rejected"))

    def count(status: str) -> ColumnElement[int]:
        return func.count().filter(AgentAction.status == status)

    rows = session.execute(
        select(
            rule,
            func.count(),
            count("approved"),
            func.count().filter(AgentAction.status == "approved", edited),
            count("rejected"),
            count("expired"),
            count("failed"),
            count("pending"),
            func.percentile_cont(0.5).within_group(func.greatest(minutes, 0)).filter(decided),
        )
        .where(*_follow_up_period(principal, filters))
        .group_by(rule)
        .order_by(rule)
    ).all()
    return Table(
        "Follow-up drafts and what people did with them",
        (
            Column("rule", "Rule"),
            Column("drafts", "Drafts", "number"),
            Column("approved", "Approved", "number"),
            Column("reworded", "Approved after rewording", "number"),
            Column("rejected", "Rejected", "number"),
            Column("expired", "Expired", "number"),
            Column("failed", "Could not be sent", "number"),
            Column("waiting", "Still waiting", "number"),
            Column("approved_share", "Approved of those decided %", "percent"),
            Column("reworded_share", "Reworded of those approved %", "percent"),
            Column("median_minutes_to_decision", "Median minutes to a decision", "number"),
        ),
        [
            {
                "rule": RULE_LABELS.get(code, code or "Unknown"),
                "drafts": drafts,
                "approved": approved,
                "reworded": reworded,
                "rejected": rejected,
                "expired": expired,
                "failed": failed,
                "waiting": waiting,
                "approved_share": percent(approved, approved + rejected),
                "reworded_share": percent(reworded, approved),
                "median_minutes_to_decision": (
                    None if median is None else Decimal(str(median)).quantize(Decimal("0.1"))
                ),
            }
            for code, drafts, approved, reworded, rejected, expired, failed, waiting, median in rows
        ],
    )


def follow_ups_sent(
    session: Session, principal: Principal, filters: Filters
) -> list[tuple[str, uuid.UUID, datetime]]:
    """Approved follow-up drafts made in the period: (rule, lead id, when approved). For the
    reports module to ask the communications module how many leads wrote back afterwards."""
    rows = session.execute(
        select(
            AgentAction.payload["reason_code"].astext,
            AgentAction.target_id,
            AgentAction.decided_at,
        ).where(
            *_follow_up_period(principal, filters),
            AgentAction.status == "approved",
            AgentAction.target_type == "lead",
            AgentAction.decided_at.is_not(None),
        )
    ).all()
    return [(code or "", lead, when) for code, lead, when in rows if when is not None]
