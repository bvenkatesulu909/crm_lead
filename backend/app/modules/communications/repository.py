"""Queries for templates and messages, always inside one tenant."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.search import escape_like
from app.modules.communications.models import EmailMessage, EmailTemplate
from app.modules.communications.policies import readable_messages, readable_templates


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


def get_readable_template(
    session: Session, principal: Principal, template_id: uuid.UUID
) -> EmailTemplate | None:
    return session.scalars(
        select(EmailTemplate).where(EmailTemplate.id == template_id, readable_templates(principal))
    ).one_or_none()


def list_templates(
    session: Session, principal: Principal, *, include_inactive: bool
) -> Sequence[EmailTemplate]:
    statement = select(EmailTemplate).where(readable_templates(principal))
    if not include_inactive:
        statement = statement.where(EmailTemplate.is_active.is_(True))
    return session.scalars(statement.order_by(EmailTemplate.name, EmailTemplate.id)).all()


def template_name_taken(
    session: Session, tenant_id: uuid.UUID, name: str, except_id: uuid.UUID | None
) -> bool:
    statement = select(EmailTemplate.id).where(
        EmailTemplate.tenant_id == tenant_id, EmailTemplate.name == name
    )
    if except_id is not None:
        statement = statement.where(EmailTemplate.id != except_id)
    return session.scalar(statement) is not None


@dataclass(frozen=True)
class MessageFilters:
    q: str | None = None
    status: str | None = None
    direction: str | None = None
    sent_by_user_id: uuid.UUID | None = None
    limit: int = 50
    offset: int = 0


def _page(
    session: Session, statement: Select[EmailMessage], limit: int, offset: int
) -> tuple[Sequence[EmailMessage], int]:
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    items = session.scalars(
        statement.order_by(EmailMessage.seq.desc()).limit(limit).offset(offset)
    ).all()
    return items, total


def search_messages(
    session: Session, principal: Principal, filters: MessageFilters
) -> tuple[Sequence[EmailMessage], int]:
    """The Communication Center list: the policy and every filter are part of the SQL query."""
    statement = select(EmailMessage).where(readable_messages(principal))
    if filters.q:
        statement = statement.where(
            EmailMessage.subject.ilike(f"%{escape_like(filters.q)}%", escape="\\")
        )
    if filters.status:
        statement = statement.where(EmailMessage.status == filters.status)
    if filters.direction:
        statement = statement.where(EmailMessage.direction == filters.direction)
    if filters.sent_by_user_id:
        statement = statement.where(EmailMessage.sent_by_user_id == filters.sent_by_user_id)
    return _page(session, statement, filters.limit, filters.offset)


def record_history(
    session: Session,
    tenant_id: uuid.UUID,
    belongs_to_record: ColumnElement[bool],
    *,
    limit: int,
    offset: int,
) -> tuple[Sequence[EmailMessage], int]:
    """Every e-mail of one record. The caller has already checked the record may be read."""
    statement = select(EmailMessage).where(EmailMessage.tenant_id == tenant_id, belongs_to_record)
    return _page(session, statement, limit, offset)
