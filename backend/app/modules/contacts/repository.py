"""Database queries for contacts. Every query goes through the contact policies."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import ColumnElement, and_, func, or_, select, update
from sqlalchemy.orm import Session

from app.core import matching
from app.core.audit import AuditLog
from app.core.auth.principal import Principal
from app.core.search import escape_like
from app.modules.contacts.models import Contact
from app.modules.contacts.policies import readable_contacts, writable_contacts

ENTITY = "contact"

_SORTS = {
    "last_name": (Contact.last_name, Contact.first_name),
    "created_at": (Contact.created_at,),
    "updated_at": (Contact.updated_at,),
}


@dataclass(frozen=True)
class ContactFilters:
    q: str | None = None
    account_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    email_consent: str | None = None
    primary_only: bool = False
    sort: str = "last_name"
    limit: int = 50
    offset: int = 0


def search(
    session: Session, principal: Principal, filters: ContactFilters
) -> tuple[Sequence[Contact], int]:
    statement = select(Contact).where(readable_contacts(principal))
    if filters.q:
        pattern = f"%{escape_like(filters.q)}%"
        statement = statement.where(
            or_(
                Contact.first_name.ilike(pattern, escape="\\"),
                Contact.last_name.ilike(pattern, escape="\\"),
                Contact.email.ilike(pattern, escape="\\"),
                Contact.phone.ilike(pattern, escape="\\"),
                Contact.mobile.ilike(pattern, escape="\\"),
                Contact.job_title.ilike(pattern, escape="\\"),
            )
        )
    if filters.account_id:
        statement = statement.where(Contact.account_id == filters.account_id)
    if filters.owner_id:
        statement = statement.where(Contact.owner_id == filters.owner_id)
    if filters.email_consent:
        statement = statement.where(Contact.email_consent == filters.email_consent)
    if filters.primary_only:
        statement = statement.where(Contact.is_primary.is_(True))
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    descending = filters.sort.startswith("-")
    columns = _SORTS[filters.sort.lstrip("-")]
    order = [c.desc() if descending else c.asc() for c in columns]
    page = statement.order_by(*order, Contact.id).limit(filters.limit).offset(filters.offset)
    return session.scalars(page).all(), total


def get_readable(session: Session, principal: Principal, contact_id: uuid.UUID) -> Contact | None:
    """The contact, or None if it does not exist OR the principal may not see it."""
    return session.scalars(
        select(Contact).where(Contact.id == contact_id, readable_contacts(principal))
    ).one_or_none()


def get_writable(session: Session, principal: Principal, contact_id: uuid.UUID) -> Contact | None:
    """The contact, locked for this transaction, if the principal may change it."""
    return session.scalars(
        select(Contact)
        .where(Contact.id == contact_id, writable_contacts(principal))
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one_or_none()


def clear_primary(
    session: Session, tenant_id: uuid.UUID, account_id: uuid.UUID, except_id: uuid.UUID
) -> list[uuid.UUID]:
    """Remove the primary flag from the other contacts of an account; returns their IDs."""
    rows = session.execute(
        update(Contact)
        .where(
            Contact.tenant_id == tenant_id,
            Contact.account_id == account_id,
            Contact.is_primary.is_(True),
            Contact.deleted_at.is_(None),
            Contact.id != except_id,
        )
        .values(is_primary=False, version=Contact.version + 1, updated_at=func.now())
        .returning(Contact.id)
        .execution_options(synchronize_session=False)
    ).all()
    return [row.id for row in rows]


def history(session: Session, contact: Contact, limit: int = 100) -> Sequence[AuditLog]:
    return session.scalars(
        select(AuditLog)
        .where(
            AuditLog.tenant_id == contact.tenant_id,
            AuditLog.entity_type == ENTITY,
            AuditLog.entity_id == contact.id,
        )
        .order_by(AuditLog.occurred_at.desc(), AuditLog.seq.desc())
        .limit(limit)
    ).all()


def visible_ids(session: Session, principal: Principal, ids: list[uuid.UUID]) -> set[uuid.UUID]:
    if not ids:
        return set()
    return set(
        session.scalars(select(Contact.id).where(Contact.id.in_(ids), readable_contacts(principal)))
    )


def duplicate_candidates(
    session: Session,
    tenant_id: uuid.UUID,
    *,
    email: str | None,
    phone: str | None,
    first_name: str | None,
    last_name: str | None,
    exclude_id: uuid.UUID | None,
    limit: int = 20,
) -> list[tuple[Contact, list[str]]]:
    """Contacts of the tenant (not archived) that may be the same person, with the reasons."""
    checks: list[tuple[ColumnElement[bool], str]] = []
    if email and email.strip():
        checks.append((func.lower(Contact.email) == email.strip().lower(), "Same e-mail"))
    if phone and (key := matching.phone_key(phone)):
        checks.append(
            (
                or_(
                    matching.phone_key_sql(Contact.phone) == key,
                    matching.phone_key_sql(Contact.mobile) == key,
                ),
                "Same phone number",
            )
        )
    if last_name and last_name.strip():
        same_last = func.lower(Contact.last_name) == last_name.strip().lower()
        first = (first_name or "").strip().lower()
        same_first = func.lower(func.coalesce(Contact.first_name, "")) == first
        checks.append((and_(same_last, same_first), "Same name"))
    if not checks:
        return []
    statement = select(Contact, *(c for c, _ in checks)).where(
        Contact.tenant_id == tenant_id, Contact.deleted_at.is_(None), or_(*(c for c, _ in checks))
    )
    if exclude_id is not None:
        statement = statement.where(Contact.id != exclude_id)
    rows = session.execute(statement.order_by(Contact.last_name).limit(limit)).all()
    return [
        (row[0], [reason for (_, reason), hit in zip(checks, row[1:], strict=True) if hit])
        for row in rows
    ]
