"""Queries of the public website chat, always inside the website's tenant (RLS is bound too)."""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.public_chat.models import PublicChatMessage, PublicChatSession


def find_session(
    session: Session, tenant_id: uuid.UUID, token_hash: str
) -> PublicChatSession | None:
    return session.scalars(
        select(PublicChatSession)
        .where(PublicChatSession.tenant_id == tenant_id, PublicChatSession.token_hash == token_hash)
        .with_for_update()  # two quick messages of one conversation are handled one after another
    ).one_or_none()


def sessions_started_since(
    session: Session, tenant_id: uuid.UUID, ip_hash: str, since: datetime
) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(PublicChatSession)
            .where(
                PublicChatSession.tenant_id == tenant_id,
                PublicChatSession.visitor_ip_hash == ip_hash,
                PublicChatSession.created_at >= since,
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
