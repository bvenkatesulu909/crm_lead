"""Document queries. Every query is limited to one tenant."""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.documents.models import Document

ATTACHMENT = "attachment"


def get(session: Session, tenant_id: uuid.UUID, document_id: uuid.UUID) -> Document | None:
    return session.scalars(
        select(Document).where(
            Document.tenant_id == tenant_id,
            Document.id == document_id,
            Document.purpose == ATTACHMENT,
        )
    ).one_or_none()


def versions(session: Session, tenant_id: uuid.UUID, group_id: uuid.UUID) -> Sequence[Document]:
    return session.scalars(
        select(Document)
        .where(Document.tenant_id == tenant_id, Document.group_id == group_id)
        .order_by(Document.version_no.desc())
    ).all()


def latest_for_record(
    session: Session, tenant_id: uuid.UUID, record_type: str, record_id: uuid.UUID
) -> list[tuple[Document, int]]:
    """Newest version of each document on a record, with its number of versions."""
    newest = (
        select(
            Document.group_id,
            func.max(Document.version_no).label("latest"),
            func.count().label("count"),
        )
        .where(
            Document.tenant_id == tenant_id,
            Document.record_type == record_type,
            Document.record_id == record_id,
            Document.purpose == ATTACHMENT,
        )
        .group_by(Document.group_id)
        .subquery()
    )
    rows = session.execute(
        select(Document, newest.c.count)
        .join(
            newest,
            (Document.group_id == newest.c.group_id) & (Document.version_no == newest.c.latest),
        )
        .where(Document.tenant_id == tenant_id)
        .order_by(Document.created_at.desc(), Document.id)
    ).all()
    return [(row[0], row[1]) for row in rows]


def group_by_name(
    session: Session, tenant_id: uuid.UUID, record_type: str, record_id: uuid.UUID, name: str
) -> tuple[uuid.UUID, int] | None:
    """(group, newest version number) of the document with this file name on the record."""
    row = session.execute(
        select(Document.group_id, func.max(Document.version_no))
        .where(
            Document.tenant_id == tenant_id,
            Document.record_type == record_type,
            Document.record_id == record_id,
            Document.purpose == ATTACHMENT,
            func.lower(Document.file_name) == name.lower(),
        )
        .group_by(Document.group_id)
        .order_by(func.max(Document.created_at).desc())
        .limit(1)
    ).first()
    return (row[0], row[1]) if row else None
