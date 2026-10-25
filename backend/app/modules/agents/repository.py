"""Queries of the agent registry. All run inside the request's tenant context (RLS, ADR 0009)."""

import uuid
from datetime import date, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modules.agents.models import AgentSetting, AgentUsage


def get_setting(
    session: Session, tenant_id: uuid.UUID, key: str, *, lock: bool = False
) -> AgentSetting | None:
    statement = select(AgentSetting).where(
        AgentSetting.tenant_id == tenant_id, AgentSetting.agent_key == key
    )
    if lock:
        statement = statement.with_for_update()
    return session.scalar(statement)


def usage_counts(
    session: Session, tenant_id: uuid.UUID, key: str, month: date
) -> tuple[int, int, int]:
    """(input tokens, output tokens, calls) of the month; zeros when nothing was recorded."""
    row = session.execute(
        select(AgentUsage.input_tokens, AgentUsage.output_tokens, AgentUsage.calls).where(
            AgentUsage.tenant_id == tenant_id,
            AgentUsage.agent_key == key,
            AgentUsage.month == month,
        )
    ).one_or_none()
    return (row[0], row[1], row[2]) if row else (0, 0, 0)


def add_usage(
    session: Session,
    tenant_id: uuid.UUID,
    key: str,
    month: date,
    input_tokens: int,
    output_tokens: int,
) -> int:
    """Add one call to the month's counts in a single atomic statement; returns the new total
    of tokens. Two calls at the same moment cannot lose each other's tokens."""
    statement = insert(AgentUsage).values(
        tenant_id=tenant_id,
        agent_key=key,
        month=month,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        calls=1,
    )
    upsert = statement.on_conflict_do_update(
        index_elements=[AgentUsage.tenant_id, AgentUsage.agent_key, AgentUsage.month],
        set_={
            "input_tokens": AgentUsage.input_tokens + input_tokens,
            "output_tokens": AgentUsage.output_tokens + output_tokens,
            "calls": AgentUsage.calls + 1,
        },
    ).returning(AgentUsage.input_tokens + AgentUsage.output_tokens)
    return int(session.execute(upsert).scalar_one())


def mark_warned(
    session: Session, tenant_id: uuid.UUID, key: str, month: date, now: datetime
) -> bool:
    """Remember that the warning went out. True only for the call that set it (once)."""
    result = session.execute(
        update(AgentUsage)
        .where(
            AgentUsage.tenant_id == tenant_id,
            AgentUsage.agent_key == key,
            AgentUsage.month == month,
            AgentUsage.warned_at.is_(None),
        )
        .values(warned_at=now)
        .returning(AgentUsage.id)
    )
    return result.first() is not None
