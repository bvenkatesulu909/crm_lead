"""Queries for templates and messages, always inside one tenant."""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.modules.communications.models import EmailMessage, EmailTemplate
from app.modules.communications.policies import readable_messages


def get_readable_message(
    session: Session, principal: Principal, message_id: uuid.UUID
) -> EmailMessage | None:
    return session.scalars(
        select(EmailMessage).where(EmailMessage.id == message_id, readable_messages(principal))
    ).one_or_none()


def get_message_for_update(
    session: Session, tenant_id: uuid.UUID, message_id: uuid.UUID
) -> EmailMessage | None:
    """For the worker: the row is locked, so two runs of the same job can't both send it."""
    return session.scalars(
        select(EmailMessage)
        .where(EmailMessage.tenant_id == tenant_id, EmailMessage.id == message_id)
        .with_for_update()
    ).one_or_none()


def sent_since(session: Session, tenant_id: uuid.UUID, user_id: uuid.UUID, since: datetime) -> int:
    """How many e-mails this person queued since ``since`` (for the hourly limit)."""
    return (
        session.scalar(
            select(func.count())
            .select_from(EmailMessage)
            .where(
                EmailMessage.tenant_id == tenant_id,
                EmailMessage.sent_by_user_id == user_id,
                EmailMessage.direction == "outbound",
                EmailMessage.created_at >= since,
            )
        )
        or 0
    )


def active_template_exists(session: Session, tenant_id: uuid.UUID, template_id: uuid.UUID) -> bool:
    return (
        session.scalar(
            select(EmailTemplate.id).where(
                EmailTemplate.tenant_id == tenant_id,
                EmailTemplate.id == template_id,
                EmailTemplate.is_active.is_(True),
            )
        )
        is not None
    )
