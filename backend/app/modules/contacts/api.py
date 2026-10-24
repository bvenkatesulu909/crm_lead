"""Public interface of the contacts module. Other modules import only from here."""

import uuid
from typing import Any

from sqlalchemy import Select, and_, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.errors import ForbiddenError
from app.core.records import Recipient
from app.core.reporting import Cell, Column, ExportFilters, ExportSpec, export_rows
from app.modules.contacts import repository
from app.modules.contacts.models import Contact
from app.modules.contacts.policies import mine, readable_contacts

__all__ = [
    "EXPORT",
    "export_table",
    "contact_account_id",
    "contact_ids_by_account",
    "contact_email",
    "contact_name",
    "contact_recipient",
    "email_consent_withdrawn",
    "create_contact",
    "is_readable_contact",
    "mine_contact_ids",
    "transfer_account_contacts",
]


def create_contact(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    first_name: str | None,
    last_name: str,
    email: str | None,
    phone: str | None,
    job_title: str | None,
    account_id: uuid.UUID | None,
    owner_id: uuid.UUID | None,
) -> uuid.UUID:
    """Insert a contact in the caller's transaction (authorization is the caller's job)."""
    contact = Contact(
        tenant_id=tenant_id,
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=phone,
        job_title=job_title,
        account_id=account_id,
        owner_id=owner_id,
    )
    session.add(contact)
    session.flush()
    return contact.id


def is_readable_contact(session: Session, principal: Principal, contact_id: uuid.UUID) -> bool:
    return repository.get_readable(session, principal, contact_id) is not None


def contact_account_id(
    session: Session, principal: Principal, contact_id: uuid.UUID
) -> tuple[bool, uuid.UUID | None]:
    """(visible?, account the contact belongs to). Invisible contacts give (False, None)."""
    contact = repository.get_readable(session, principal, contact_id)
    return (False, None) if contact is None else (True, contact.account_id)


def mine_contact_ids(principal: Principal) -> Select[uuid.UUID]:
    """Subquery: contacts the user owns or that work at an account the user owns."""
    return select(Contact.id).where(
        and_(
            Contact.tenant_id == principal.tenant_id,
            Contact.deleted_at.is_(None),
            mine(principal),
        )
    )


def contact_ids_by_account(
    session: Session, tenant_id: uuid.UUID, account_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[uuid.UUID]]:
    """IDs of the (not archived) contacts of each account."""
    result: dict[uuid.UUID, list[uuid.UUID]] = {a: [] for a in account_ids}
    if account_ids:
        rows = session.execute(
            select(Contact.id, Contact.account_id).where(
                Contact.tenant_id == tenant_id,
                Contact.account_id.in_(account_ids),
                Contact.deleted_at.is_(None),
            )
        )
        for contact_id, account_id in rows:
            if account_id is not None:
                result[account_id].append(contact_id)
    return result


def transfer_account_contacts(
    session: Session,
    principal: Principal,
    account_id: uuid.UUID,
    from_owner: uuid.UUID | None,
    to_owner: uuid.UUID,
) -> list[uuid.UUID]:
    """Give the account's contacts that belonged to the previous account owner to the new one.
    Contacts owned by someone else stay theirs. Each change is audited."""
    owned_by_previous = (
        Contact.owner_id.is_(None) if from_owner is None else Contact.owner_id == from_owner
    )
    contacts = session.scalars(
        select(Contact)
        .where(
            Contact.tenant_id == principal.tenant_id,
            Contact.account_id == account_id,
            Contact.deleted_at.is_(None),
            owned_by_previous,
        )
        .with_for_update()
    ).all()
    for contact in contacts:
        contact.owner_id = to_owner
        record_audit(
            session,
            principal,
            action="contact.updated",
            entity_type="contact",
            entity_id=contact.id,
            changes={
                "owner_id": {"old": from_owner, "new": to_owner},
                "reason": "Account transfer",
            },
        )
    session.flush()
    return [c.id for c in contacts]


def contact_recipient(
    session: Session, principal: Principal, contact_id: uuid.UUID
) -> Recipient | None:
    """Who to write to (Communication Center), if this principal may see the contact."""
    contact = repository.get_readable(session, principal, contact_id)
    if contact is None:
        return None
    return Recipient(
        first_name=contact.first_name,
        full_name=" ".join(p for p in (contact.first_name, contact.last_name) if p),
        email=contact.email,
        account_id=contact.account_id,
        consent_withdrawn=contact.email_consent == "withdrawn",
    )


def email_consent_withdrawn(session: Session, tenant_id: uuid.UUID, contact_id: uuid.UUID) -> bool:
    """True if the contact has withdrawn e-mail consent (or no longer exists), checked by the
    worker just before sending. No record policy: the e-mail was authorized when it was queued."""
    consent = session.scalar(
        select(Contact.email_consent).where(
            Contact.tenant_id == tenant_id,
            Contact.id == contact_id,
            Contact.deleted_at.is_(None),
        )
    )
    return consent is None or consent == "withdrawn"


def contact_name(session: Session, tenant_id: uuid.UUID, contact_id: uuid.UUID) -> str | None:
    """A contact's full name, for system-generated documents (e.g. a quote PDF).
    No record policy: callers must already have authorized the record that needs it."""
    row = session.execute(
        select(Contact.first_name, Contact.last_name).where(
            Contact.tenant_id == tenant_id, Contact.id == contact_id
        )
    ).first()
    return " ".join(p for p in (row.first_name, row.last_name) if p) if row else None


def contact_email(
    session: Session, tenant_id: uuid.UUID, contact_id: uuid.UUID
) -> tuple[str, str] | None:
    """(full name, e-mail) of an active contact that has an e-mail address, else None.
    For system e-mails about an already-authorized record (e.g. a quote); no record policy."""
    row = session.execute(
        select(Contact.first_name, Contact.last_name, Contact.email).where(
            Contact.tenant_id == tenant_id,
            Contact.id == contact_id,
            Contact.deleted_at.is_(None),
            Contact.email.is_not(None),
        )
    ).first()
    if row is None or not row.email:
        return None
    return " ".join(p for p in (row.first_name, row.last_name) if p), row.email


# Report builder (Phase 18): the columns that may be exported - never internal notes - and the
# statuses to filter by. Rows always pass through this module's own record-level policy.
EXPORT = ExportSpec(
    columns=(
        Column("created_at", "Created", "datetime"),
        Column("first_name", "First name", "text"),
        Column("last_name", "Last name", "text"),
        Column("job_title", "Job title", "text"),
        Column("email", "E-mail", "text"),
        Column("phone", "Phone", "text"),
        Column("mobile", "Mobile", "text"),
        Column("account_id", "Account", "account"),
        Column("email_consent", "E-mail consent", "text"),
        Column("owner_id", "Owner", "user"),
    ),
    statuses=(),
)


def export_table(
    session: Session, principal: Principal, filters: ExportFilters, wanted: list[str]
) -> list[dict[str, Cell]]:
    allowed = {c.key for c in EXPORT.columns}
    if not wanted or not set(wanted) <= allowed:
        raise ValueError("unknown export column")
    return export_rows(
        session,
        entity=Contact,
        columns={key: getattr(Contact, key) for key in allowed},
        wanted=wanted,
        condition=readable_contacts(principal),
        created=Contact.created_at,
        owner=Contact.owner_id,
        status=None,
        filters=filters,
    )


# --- customer portal (AI assistant) ---------------------------------------------------------


def customer_contacts(
    session: Session, principal: Principal, *, limit: int = 50
) -> list[dict[str, Any]]:
    """Contacts of the customer's granted accounts only; no consent/owner internals."""
    if principal.user_type != "customer" or principal.tenant_id is None:
        raise ForbiddenError("Only customers can list their contacts.")
    from app.modules.identity.api import granted_account_ids

    rows = session.scalars(
        select(Contact)
        .where(
            Contact.tenant_id == principal.tenant_id,
            Contact.account_id.in_(granted_account_ids(principal)),
        )
        .order_by(Contact.last_name, Contact.first_name)
        .limit(min(limit, 100))
    ).all()
    return [
        {
            "name": " ".join(part for part in (c.first_name, c.last_name) if part),
            "email": c.email,
            "phone": c.phone,
            "job_title": c.job_title,
            "account_id": str(c.account_id) if c.account_id else None,
        }
        for c in rows
    ]


# --- staff assistant (read-only, record-policy enforced) -------------------------------------


def list_account_contacts(
    session: Session, principal: Principal, account_id: uuid.UUID, *, limit: int = 20
) -> list[dict[str, Any]]:
    from app.modules.contacts import service as contact_service
    from app.modules.contacts.repository import ContactFilters

    items, _ = contact_service.list_contacts(
        session, principal, ContactFilters(account_id=account_id, limit=min(limit, 50))
    )
    return [
        {
            "id": str(item.id),
            "name": " ".join(part for part in (item.first_name, item.last_name) if part),
            "email": item.email,
            "phone": item.phone,
            "job_title": item.job_title,
            "account_id": str(item.account_id) if item.account_id else None,
        }
        for item in items
    ]
