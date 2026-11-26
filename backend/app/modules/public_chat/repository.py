"""Queries of the public website chat, always inside the website's tenant (RLS is bound too)."""

import uuid
from collections.abc import Sequence
from datetime import date, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modules.public_chat.models import (
    PublicChatDailyStat,
    PublicChatMessage,
    PublicChatSession,
)


def find_session(
    session: Session, tenant_id: uuid.UUID, token_hash: str
) -> PublicChatSession | None:
    return session.scalars(
        select(PublicChatSession)
        .where(PublicChatSession.tenant_id == tenant_id, PublicChatSession.token_hash == token_hash)
        .with_for_update()  # two quick messages of one conversation are handled one after another
    ).one_or_none()


def get_session(
    session: Session, tenant_id: uuid.UUID, session_id: uuid.UUID
) -> PublicChatSession | None:
    return session.scalars(
        select(PublicChatSession).where(
            PublicChatSession.tenant_id == tenant_id, PublicChatSession.id == session_id
        )
    ).one_or_none()


def sessions_started_since(
    session: Session,
    tenant_id: uuid.UUID,
    ip_hash: str,
    since: datetime,
    *,
    channel: str | None = None,
) -> int:
    """Conversations an address started since ``since``; with ``channel`` only that kind."""
    statement = (
        select(func.count())
        .select_from(PublicChatSession)
        .where(
            PublicChatSession.tenant_id == tenant_id,
            PublicChatSession.visitor_ip_hash == ip_hash,
            PublicChatSession.created_at >= since,
        )
    )
    if channel is not None:
        statement = statement.where(PublicChatSession.channel == channel)
    return session.scalar(statement) or 0


def find_session_unlocked(
    session: Session, tenant_id: uuid.UUID, token_hash: str
) -> PublicChatSession | None:
    """Like ``find_session`` but without the row lock: for checks that run before the work."""
    return session.scalars(
        select(PublicChatSession).where(
            PublicChatSession.tenant_id == tenant_id, PublicChatSession.token_hash == token_hash
        )
    ).one_or_none()


def voice_seconds_between(session: Session, tenant_id: uuid.UUID, first: date, last: date) -> int:
    """The organisation's server-speech seconds from day ``first`` to day ``last`` inclusive."""
    return int(
        session.scalar(
            select(func.coalesce(func.sum(PublicChatDailyStat.voice_seconds), 0)).where(
                PublicChatDailyStat.tenant_id == tenant_id,
                PublicChatDailyStat.day >= first,
                PublicChatDailyStat.day <= last,
            )
        )
        or 0
    )


def visitor_messages_since(
    session: Session,
    tenant_id: uuid.UUID,
    since: datetime,
    *,
    ip_hash: str | None = None,
) -> int:
    """Visitor messages of the tenant since ``since``; with ``ip_hash`` only that address's."""
    statement = (
        select(func.count())
        .select_from(PublicChatMessage)
        .where(
            PublicChatMessage.tenant_id == tenant_id,
            PublicChatMessage.role == "visitor",
            PublicChatMessage.created_at >= since,
        )
    )
    if ip_hash is not None:
        statement = statement.join(
            PublicChatSession,
            (PublicChatSession.tenant_id == PublicChatMessage.tenant_id)
            & (PublicChatSession.id == PublicChatMessage.session_id),
        ).where(PublicChatSession.visitor_ip_hash == ip_hash)
    return session.scalar(statement) or 0


def visitor_messages_in(session: Session, conversation: PublicChatSession) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(PublicChatMessage)
            .where(
                PublicChatMessage.tenant_id == conversation.tenant_id,
                PublicChatMessage.session_id == conversation.id,
                PublicChatMessage.role == "visitor",
            )
        )
        or 0
    )


def recent_messages(
    session: Session, conversation: PublicChatSession, limit: int
) -> Sequence[PublicChatMessage]:
    """The newest ``limit`` messages, oldest first."""
    newest = session.scalars(
        select(PublicChatMessage)
        .where(
            PublicChatMessage.tenant_id == conversation.tenant_id,
            PublicChatMessage.session_id == conversation.id,
        )
        .order_by(PublicChatMessage.seq.desc())
        .limit(limit)
    ).all()
    return list(reversed(newest))


def session_of_lead(
    session: Session, tenant_id: uuid.UUID, lead_id: uuid.UUID
) -> PublicChatSession | None:
    """The conversation that created this lead (each conversation saves at most one lead)."""
    return session.scalars(
        select(PublicChatSession)
        .where(PublicChatSession.tenant_id == tenant_id, PublicChatSession.lead_id == lead_id)
        .order_by(PublicChatSession.created_at)
        .limit(1)
    ).one_or_none()


def all_messages(session: Session, conversation: PublicChatSession) -> Sequence[PublicChatMessage]:
    """Every message, oldest first (a conversation is capped at 30 visitor messages)."""
    return session.scalars(
        select(PublicChatMessage)
        .where(
            PublicChatMessage.tenant_id == conversation.tenant_id,
            PublicChatMessage.session_id == conversation.id,
        )
        .order_by(PublicChatMessage.seq)
    ).all()


def delete_stale(session: Session, tenant_id: uuid.UUID, before: datetime) -> int:
    """Delete conversations without a lead that were quiet since ``before``, with their
    messages. Returns how many conversations went."""
    stale = select(PublicChatSession.id).where(
        PublicChatSession.tenant_id == tenant_id,
        PublicChatSession.lead_id.is_(None),
        PublicChatSession.updated_at < before,
    )
    session.execute(
        delete(PublicChatMessage).where(
            PublicChatMessage.tenant_id == tenant_id, PublicChatMessage.session_id.in_(stale)
        )
    )
    result = session.execute(
        delete(PublicChatSession).where(
            PublicChatSession.tenant_id == tenant_id, PublicChatSession.id.in_(stale)
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)


def count_event(
    session: Session,
    tenant_id: uuid.UUID,
    day: date,
    *,
    started: int = 0,
    leads: int = 0,
    voice_seconds: int = 0,
) -> None:
    """Add to the day's anonymous counters in ONE statement, so two requests at the same moment
    add up instead of one overwriting the other."""
    stat = insert(PublicChatDailyStat).values(
        tenant_id=tenant_id,
        day=day,
        conversations_started=started,
        leads_saved=leads,
        voice_seconds=voice_seconds,
    )
    session.execute(
        stat.on_conflict_do_update(
            index_elements=[PublicChatDailyStat.tenant_id, PublicChatDailyStat.day],
            set_={
                "conversations_started": PublicChatDailyStat.conversations_started
                + stat.excluded.conversations_started,
                "leads_saved": PublicChatDailyStat.leads_saved + stat.excluded.leads_saved,
                "voice_seconds": PublicChatDailyStat.voice_seconds + stat.excluded.voice_seconds,
                "updated_at": func.now(),
            },
        )
    )
