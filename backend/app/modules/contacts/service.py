"""Contact business rules. Functions here never commit: the router commits once.

Every change writes an ``audit_log`` row (the contact's history). Changes that matter to the
customer account - a contact added, moved away, archived or made primary - are also noted on
the account's timeline through ``accounts.api.record_account_event``.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.audit import diff, record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import SALES_ROLES, Permission
from app.core.errors import ConflictError, DomainError, ForbiddenError, NotFoundError
from app.modules.accounts import api as accounts_api
from app.modules.contacts import repository
from app.modules.contacts.models import Contact
from app.modules.contacts.repository import ENTITY, ContactFilters
from app.modules.contacts.schemas import (
    ContactCreate,
    ContactDuplicate,
    ContactDuplicateCheck,
    ContactUpdate,
    HistoryEntry,
)
from app.modules.identity import api as identity_api

_FIELDS = (
    "first_name",
    "last_name",
    "email",
    "phone",
    "mobile",
    "job_title",
    "department",
    "account_id",
    "owner_id",
    "is_primary",
    "preferred_channel",
    "email_consent",
    "do_not_call",
    "preferred_language",
)


class ContactNotFoundError(NotFoundError):
    code = "contact_not_found"

    def __init__(self) -> None:
        super().__init__("Contact not found.")


class ContactAccountNotFoundError(NotFoundError):
    """The account to link doesn't exist, is in another tenant or isn't visible to you."""

    code = "account_not_found"

    def __init__(self) -> None:
        super().__init__("Account not found.")


class VersionConflictError(ConflictError):
    code = "version_conflict"


class InvalidContactError(DomainError):
    status_code = 422
    code = "invalid_contact"


# --- helpers ----------------------------------------------------------------------------


def _tenant(principal: Principal) -> uuid.UUID:
    if principal.tenant_id is None or principal.user_type != "staff":
        raise ForbiddenError("Only staff of an organisation can change contacts.")
    return principal.tenant_id


def _name(contact: Contact) -> str:
    return " ".join(p for p in (contact.first_name, contact.last_name) if p)


def _snapshot(contact: Contact) -> dict[str, object]:
    return {field: getattr(contact, field) for field in _FIELDS}


def _flush(session: Session) -> None:
    try:
        session.flush()
    except StaleDataError as exc:
        raise VersionConflictError(
            "The contact was changed by someone else. Reload it and try again."
        ) from exc


def _check_account(session: Session, principal: Principal, account_id: uuid.UUID) -> None:
    if not accounts_api.is_readable_account(session, principal, account_id):
        raise ContactAccountNotFoundError()


def _check_owner(session: Session, principal: Principal, owner_id: uuid.UUID) -> None:
    if owner_id != principal.user_id and not principal.has_permission(Permission.CONTACT_WRITE_ALL):
        raise ForbiddenError("You may not give contacts to other people.")
    if not identity_api.is_assignable_sales_user(session, _tenant(principal), owner_id):
        raise InvalidContactError(
            "The owner must be an active sales employee of your organisation."
        )


def _make_primary(
    session: Session,
    principal: Principal,
    *,
    tenant_id: uuid.UUID,
    account_id: uuid.UUID | None,
    contact_id: uuid.UUID,
    contact_name: str,
) -> None:
    """Take the primary flag away from the account's other contacts. Called BEFORE this contact
    is saved as primary, so the one-primary-per-account index is never violated and the
    contact is written once (one version step)."""
    if account_id is None:
        raise InvalidContactError("Only a contact linked to an account can be its primary contact.")
    previous = repository.clear_primary(session, tenant_id, account_id, contact_id)
    for other in previous:
        record_audit(
            session,
            principal,
            action="contact.updated",
            entity_type=ENTITY,
            entity_id=other,
            changes={"is_primary": {"old": True, "new": False}},
        )
    accounts_api.record_account_event(
        session,
        principal,
        account_id,
        "account.primary_contact_changed",
        {"contact_id": contact_id, "contact_name": contact_name},
    )


def _account_event(
    session: Session, principal: Principal, account_id: uuid.UUID, action: str, contact: Contact
) -> None:
    accounts_api.record_account_event(
        session,
        principal,
        account_id,
        action,
        {"contact_id": contact.id, "contact_name": _name(contact)},
    )


# --- use cases --------------------------------------------------------------------------


def create_contact(session: Session, principal: Principal, data: ContactCreate) -> Contact:
    tenant_id = _tenant(principal)
    if data.owner_id is not None:
        _check_owner(session, principal, data.owner_id)
        owner_id: uuid.UUID | None = data.owner_id
    elif principal.roles & SALES_ROLES:
        owner_id = principal.user_id
    else:
        owner_id = None
    if data.account_id is not None:
        _check_account(session, principal, data.account_id)
    elif data.is_primary:
        raise InvalidContactError("Only a contact linked to an account can be its primary contact.")

    values = data.model_dump(exclude={"owner_id"}, exclude_none=True)
    contact = Contact(id=uuid.uuid4(), tenant_id=tenant_id, owner_id=owner_id, **values)
    if contact.email_consent not in (None, "unknown"):
        contact.email_consent_at = datetime.now(UTC)
    # Timeline order: first "contact added", then (if so) "primary contact changed".
    if contact.account_id is not None:
        _account_event(session, principal, contact.account_id, "account.contact_added", contact)
    if data.is_primary:
        _make_primary(
            session,
            principal,
            tenant_id=tenant_id,
            account_id=contact.account_id,
            contact_id=contact.id,
            contact_name=_name(contact),
        )
    session.add(contact)
    session.flush()
    session.refresh(contact)  # server defaults (consent "unknown", flags) for the snapshot
    record_audit(
        session,
        principal,
        action="contact.created",
        entity_type=ENTITY,
        entity_id=contact.id,
        changes=diff({}, _snapshot(contact)),
    )
    _flush(session)
    return contact


def get_contact(session: Session, principal: Principal, contact_id: uuid.UUID) -> Contact:
    contact = repository.get_readable(session, principal, contact_id)
    if contact is None:
        raise ContactNotFoundError()
    return contact


def list_contacts(
    session: Session, principal: Principal, filters: ContactFilters
) -> tuple[Sequence[Contact], int]:
    return repository.search(session, principal, filters)


def _load_for_write(session: Session, principal: Principal, contact_id: uuid.UUID) -> Contact:
    contact = repository.get_writable(session, principal, contact_id)
    if contact is None:
        if repository.get_readable(session, principal, contact_id) is not None:
            raise ForbiddenError("You may view this contact but not change it.")
        raise ContactNotFoundError()
    return contact


def update_contact(
    session: Session, principal: Principal, contact_id: uuid.UUID, data: ContactUpdate
) -> Contact:
    contact = _load_for_write(session, principal, contact_id)
    if contact.version != data.version:
        raise VersionConflictError(
            f"The contact was changed by someone else (now version {contact.version}). Reload it."
        )
    changes = data.changes()
    if "owner_id" in changes and changes["owner_id"] != contact.owner_id:
        if not principal.has_permission(Permission.CONTACT_WRITE_ALL):
            raise ForbiddenError("Only managers and administrators can change the owner.")
        if data.owner_id is not None:
            _check_owner(session, principal, data.owner_id)
    old_account = contact.account_id
    moved = "account_id" in changes and changes["account_id"] != old_account
    if moved and data.account_id is not None:
        _check_account(session, principal, data.account_id)
    if moved and "is_primary" not in changes:
        changes["is_primary"] = False  # it was the primary of the old account, not the new one
    target_account = changes.get("account_id", old_account)
    if moved:
        if old_account is not None:
            _account_event(session, principal, old_account, "account.contact_removed", contact)
        if target_account is not None:
            _account_event(
                session,
                principal,
                target_account,  # type: ignore[arg-type]
                "account.contact_added",
                contact,
            )
    if changes.get("is_primary") is True and (not contact.is_primary or moved):
        # Clear the account's current primary first (before this contact is changed at all).
        _make_primary(
            session,
            principal,
            tenant_id=contact.tenant_id,
            account_id=target_account,  # type: ignore[arg-type]
            contact_id=contact.id,
            contact_name=_name(contact),
        )

    before = _snapshot(contact)
    for field, value in changes.items():
        setattr(contact, field, value)
    if contact.is_primary and contact.account_id is None:
        raise InvalidContactError("Only a contact linked to an account can be its primary contact.")
    if before["email_consent"] != contact.email_consent:
        contact.email_consent_at = None if contact.email_consent == "unknown" else datetime.now(UTC)
    changed = diff(before, _snapshot(contact))
    if changed:
        record_audit(
            session,
            principal,
            action="contact.updated",
            entity_type=ENTITY,
            entity_id=contact.id,
            changes=changed,
        )
    _flush(session)
    return contact


def archive_contact(
    session: Session,
    principal: Principal,
    contact_id: uuid.UUID,
    *,
    version: int,
    reason: str | None,
) -> Contact:
    contact = _load_for_write(session, principal, contact_id)
    if contact.version != version:
        raise VersionConflictError(
            f"The contact was changed by someone else (now version {contact.version}). Reload it."
        )
    contact.deleted_at = datetime.now(UTC)
    contact.is_primary = False
    record_audit(
        session,
        principal,
        action="contact.archived",
        entity_type=ENTITY,
        entity_id=contact.id,
        changes={"reason": reason},
    )
    if contact.account_id is not None:
        _account_event(session, principal, contact.account_id, "account.contact_removed", contact)
    _flush(session)
    return contact


_TITLES = {
    "contact.created": "Contact created",
    "contact.updated": "Details changed",
    "contact.archived": "Contact archived",
}


def contact_history(
    session: Session, principal: Principal, contact_id: uuid.UUID
) -> list[HistoryEntry]:
    contact = get_contact(session, principal, contact_id)
    rows = repository.history(session, contact)
    people = identity_api.people_by_id(
        session, contact.tenant_id, {r.actor_user_id for r in rows if r.actor_user_id}
    )
    return [
        HistoryEntry(
            at=row.occurred_at,
            action=row.action,
            title=_TITLES.get(row.action, row.action),
            changes=row.changes,
            actor_name=people.get(row.actor_user_id, ("Former colleague", ""))[0]
            if row.actor_user_id
            else None,
        )
        for row in rows
    ]


def check_duplicates(
    session: Session,
    principal: Principal,
    *,
    email: str | None,
    phone: str | None,
    first_name: str | None,
    last_name: str | None,
    exclude_id: uuid.UUID | None,
) -> ContactDuplicateCheck:
    """Possible matches before creating a contact. Like accounts: the whole organisation is
    searched, only visible contacts are named, the rest are counted."""
    tenant_id = _tenant(principal)
    found = repository.duplicate_candidates(
        session,
        tenant_id,
        email=email,
        phone=phone,
        first_name=first_name,
        last_name=last_name,
        exclude_id=exclude_id,
    )
    visible = repository.visible_ids(session, principal, [c.id for c, _ in found])
    return ContactDuplicateCheck(
        candidates=[
            ContactDuplicate(
                id=c.id, name=_name(c), email=c.email, account_id=c.account_id, reasons=reasons
            )
            for c, reasons in found
            if c.id in visible
        ],
        hidden_matches=sum(1 for c, _ in found if c.id not in visible),
    )
