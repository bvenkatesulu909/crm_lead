"""Queries of the custom agents. Every query names the organisation (row-level security is the
second wall, ADR 0009)."""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.custom_agents.models import CustomAgent, CustomAgentRun, CustomAgentVersion


def get(
    session: Session, tenant_id: uuid.UUID, agent_id: uuid.UUID, *, lock: bool = False
) -> CustomAgent | None:
    query = select(CustomAgent).where(
        CustomAgent.tenant_id == tenant_id, CustomAgent.id == agent_id
    )
    if lock:
        query = query.with_for_update()
    return session.scalars(query).first()


def get_by_key(session: Session, tenant_id: uuid.UUID, key: str) -> CustomAgent | None:
    return session.scalars(
        select(CustomAgent).where(CustomAgent.tenant_id == tenant_id, CustomAgent.agent_key == key)
    ).first()


def list_agents(
    session: Session, tenant_id: uuid.UUID, *, include_archived: bool = False
) -> list[CustomAgent]:
    query = select(CustomAgent).where(CustomAgent.tenant_id == tenant_id)
    if not include_archived:
        query = query.where(CustomAgent.archived_at.is_(None))
    return list(session.scalars(query.order_by(CustomAgent.created_at, CustomAgent.id)))


def count_active(session: Session, tenant_id: uuid.UUID) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(CustomAgent)
            .where(CustomAgent.tenant_id == tenant_id, CustomAgent.archived_at.is_(None))
        )
        or 0
    )


def name_taken(
    session: Session, tenant_id: uuid.UUID, name: str, *, except_id: uuid.UUID | None = None
) -> bool:
    """A name is used once per organisation among the agents that are not archived, ignoring
    capitals."""
    query = (
        select(func.count())
        .select_from(CustomAgent)
        .where(
            CustomAgent.tenant_id == tenant_id,
            CustomAgent.archived_at.is_(None),
            func.lower(CustomAgent.name) == name.lower(),
        )
    )
    if except_id is not None:
        query = query.where(CustomAgent.id != except_id)
    return bool(session.scalar(query))


def get_version(
    session: Session, tenant_id: uuid.UUID, agent_id: uuid.UUID, version_no: int
) -> CustomAgentVersion | None:
    return session.scalars(
        select(CustomAgentVersion).where(
            CustomAgentVersion.tenant_id == tenant_id,
            CustomAgentVersion.custom_agent_id == agent_id,
            CustomAgentVersion.version_no == version_no,
        )
    ).first()


def list_versions(
    session: Session, tenant_id: uuid.UUID, agent_id: uuid.UUID
) -> list[CustomAgentVersion]:
    return list(
        session.scalars(
            select(CustomAgentVersion)
            .where(
                CustomAgentVersion.tenant_id == tenant_id,
                CustomAgentVersion.custom_agent_id == agent_id,
            )
            .order_by(CustomAgentVersion.version_no.desc())
        )
    )


def add_run(session: Session, run: CustomAgentRun) -> CustomAgentRun:
    session.add(run)
    session.flush()
    return run


def count_runs(
    session: Session,
    tenant_id: uuid.UUID,
    *,
    since: datetime,
    record_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    real_only: bool = False,
) -> int:
    """Runs (and dry runs, unless ``real_only``) since a moment, for the rate limits."""
    query = (
        select(func.count())
        .select_from(CustomAgentRun)
        .where(CustomAgentRun.tenant_id == tenant_id, CustomAgentRun.created_at >= since)
    )
    if record_id is not None:
        query = query.where(CustomAgentRun.record_id == record_id)
    if user_id is not None:
        query = query.where(CustomAgentRun.user_id == user_id)
    if real_only:
        query = query.where(CustomAgentRun.mode == "run")
    return int(session.scalar(query) or 0)


def has_trial(session: Session, tenant_id: uuid.UUID, agent_id: uuid.UUID, version_no: int) -> bool:
    """Has this version of the agent had a successful dry run?"""
    return bool(
        session.scalar(
            select(func.count())
            .select_from(CustomAgentRun)
            .where(
                CustomAgentRun.tenant_id == tenant_id,
                CustomAgentRun.custom_agent_id == agent_id,
                CustomAgentRun.version_no == version_no,
                CustomAgentRun.mode == "trial",
            )
        )
    )


def list_runs(
    session: Session, tenant_id: uuid.UUID, agent_id: uuid.UUID, *, limit: int = 50
) -> list[CustomAgentRun]:
    return list(
        session.scalars(
            select(CustomAgentRun)
            .where(
                CustomAgentRun.tenant_id == tenant_id, CustomAgentRun.custom_agent_id == agent_id
            )
            .order_by(CustomAgentRun.seq.desc())
            .limit(limit)
        )
    )
