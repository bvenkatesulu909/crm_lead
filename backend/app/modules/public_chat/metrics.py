"""Figures of the website chat for the "Website chat" report (docs/pilot-report.md).

Aggregates only: how many conversations started and how many produced a lead (from the anonymous
daily counters, which outlive the clean-up of conversations), and how long the visitors who did
leave their details took from their first message to the saved lead.
"""

import math
import statistics

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.reporting import Column, Filters, Table, percent
from app.modules.leads import api as leads_api
from app.modules.public_chat.models import (
    PublicChatDailyStat,
    PublicChatMessage,
    PublicChatSession,
)


def _seconds_to_lead(session: Session, principal: Principal, filters: Filters) -> list[int]:
    """Seconds from the visitor's first message to the lead, for the leads made in the period
    (only conversations that became a lead are kept, so this is always complete)."""
    first_message = (
        select(func.min(PublicChatMessage.created_at))
        .where(
            PublicChatMessage.session_id == PublicChatSession.id,
            PublicChatMessage.role == "visitor",
        )
        .scalar_subquery()
    )
    rows = session.execute(
        select(PublicChatSession.lead_id, first_message).where(
            PublicChatSession.lead_id.is_not(None)
        )
    ).all()
    made = leads_api.created_at_of(
        session, principal, [lead_id for lead_id, _ in rows if lead_id is not None]
    )
    seconds: list[int] = []
    for lead_id, started in rows:
        created = made.get(lead_id) if lead_id is not None else None
        if created is None or started is None:
            continue
        if filters.period.start <= created < filters.period.end:
            seconds.append(max(0, round((created - started).total_seconds())))
    return seconds


def _nearest_rank(values: list[int], share: float) -> int:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)]


def funnel_table(session: Session, principal: Principal, filters: Filters) -> Table:
    period = filters.period
    started, leads = session.execute(
        select(
            func.coalesce(func.sum(PublicChatDailyStat.conversations_started), 0),
            func.coalesce(func.sum(PublicChatDailyStat.leads_saved), 0),
        ).where(
            PublicChatDailyStat.day >= period.start_date,
            PublicChatDailyStat.day <= period.end_date,
        )
    ).one()
    started, leads = int(started), int(leads)
    seconds = _seconds_to_lead(session, principal, filters)
    return Table(
        "Website chat: conversations and leads (whole organisation)",
        (
            Column("started", "Conversations started", "number"),
            Column("leads", "Leads saved", "number"),
            Column("lead_share", "Ended with a lead %", "percent"),
            Column("measured", "Leads timed", "number"),
            Column("median_seconds_to_lead", "Median seconds to the lead", "number"),
            Column("p90_seconds_to_lead", "90% were done within (seconds)", "number"),
        ),
        [
            {
                "started": started,
                "leads": leads,
                "lead_share": percent(leads, started),
                "measured": len(seconds),
                "median_seconds_to_lead": round(statistics.median(seconds)) if seconds else None,
                "p90_seconds_to_lead": _nearest_rank(seconds, 0.9) if seconds else None,
            }
        ],
    )


__all__ = ["funnel_table"]
