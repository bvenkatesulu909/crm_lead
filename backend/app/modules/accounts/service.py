"""Account business rules. Functions here never commit: the router commits once, so every
request is one transaction that either fully happens or not at all.

Every change writes an ``audit_log`` row (who, what, old -> new) in the same transaction; the
account timeline is read back from those rows.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.audit import AuditLog, diff, record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import SALES_ROLES, Permission
from app.core.errors import ConflictError, DomainError, ForbiddenError, NotFoundError
from app.modules.accounts import repository
from app.modules.accounts.models import ACCOUNT_SEGMENTS, Account
from app.modules.accounts.policies import can_write, readable_accounts
from app.modules.accounts.repository import ENTITY, AccountFilters
from app.modules.accounts.schemas import (
    AccountCreate,
    AccountUpdate,
    DuplicateCandidate,
    DuplicateCheck,
    TimelineEntry,
)
from app.modules.identity import api as identity_api

_DETAIL_FIELDS = (
    "name",
    "account_number",
    "website",
    "industry",
    "phone",
    "segment",
    "preferred_channel",
    "country",
    "region",
    "city",
    "lifecycle_stage",
    "account_type",
    "preferred_language",
    "parent_account_id",
    "owner_id",
)
MAX_HIERARCHY_DEPTH = 10


class AccountNotFoundError(NotFoundError):
    code = "account_not_found"

    def __init__(self, what: str = "Account") -> None:
        # Same message whether it doesn't exist, belongs to another tenant or isn't yours.
        super().__init__(f"{what} not found.")


class VersionConflictError(ConflictError):
    code = "version_conflict"


class AccountNumberTakenError(ConflictError):
    code = "account_number_taken"


class InvalidHierarchyError(DomainError):
    status_code = 422
    code = "invalid_hierarchy"


class InvalidSegmentError(DomainError):
    status_code = 422
    code = "invalid_segment"


class InvalidOwnerError(DomainError):
    status_code = 422
    code = "invalid_owner"


class AccountStateError(ConflictError):
    code = "account_state"


# --- helpers ----------------------------------------------------------------------------


def _tenant(principal: Principal) -> uuid.UUID:
    if principal.tenant_id is None or principal.user_type != "staff":
        raise ForbiddenError("Only staff of an organisation can change accounts.")
    return principal.tenant_id


def _snapshot(account: Account) -> dict[str, object]:
    return {field: getattr(account, field) for field in _DETAIL_FIELDS}


def _audit(
    session: Session,
    principal: Principal,
    account_id: uuid.UUID,
    action: str,
    changes: dict[str, Any],
) -> None:
    record_audit(
        session,
        principal,
        action=action,
        entity_type=ENTITY,
        entity_id=account_id,
        changes=changes,
    )


def _flush(session: Session) -> None:
    try:
        session.flush()
    except StaleDataError as exc:
        raise VersionConflictError(
            "The account was changed by someone else. Reload it and try again."
        ) from exc


def _load_for_write(session: Session, principal: Principal, account_id: uuid.UUID) -> Account:
    account = repository.get_readable(session, principal, account_id, for_update=True)
    if account is None:
        raise AccountNotFoundError()
    if not can_write(principal, account):
        raise ForbiddenError("You may view this account but not change it.")
    return account


def _check_version(account: Account, version: int) -> None:
    if account.version != version:
        raise VersionConflictError(
            f"The account was changed by someone else (now version {account.version}). Reload it."
        )


def _check_owner(session: Session, principal: Principal, owner_id: uuid.UUID | None) -> None:
    if owner_id != principal.user_id and not principal.has_permission(Permission.ACCOUNT_WRITE_ALL):
        raise ForbiddenError("You may not give accounts to other people.")
    if owner_id is not None and not identity_api.is_assignable_sales_user(
        session, _tenant(principal), owner_id
    ):
        raise InvalidOwnerError("The owner must be an active sales employee of your organisation.")


def _check_number(
    session: Session, tenant_id: uuid.UUID, number: str | None, except_id: uuid.UUID | None
) -> None:
    if number and repository.number_taken(session, tenant_id, number, except_id):
        raise AccountNumberTakenError("Another account already uses this account number.")


def _check_parent(
    session: Session, principal: Principal, parent_id: uuid.UUID, account: Account | None
) -> None:
    parent = repository.get_readable(session, principal, parent_id)
    if parent is None:
        raise AccountNotFoundError("Parent account")
    if account is None:
        depth = len(repository.ancestor_ids(session, parent)) + 1
    else:
        if parent.id == account.id:
            raise InvalidHierarchyError("An account cannot be its own parent.")
        above = repository.ancestor_ids(session, parent)
        if account.id in above:
            raise InvalidHierarchyError(
                "This would create a loop: the chosen parent belongs to this account."
            )
        depth = len(above) + 1
    if depth >= MAX_HIERARCHY_DEPTH:
        raise InvalidHierarchyError(f"Hierarchies can be at most {MAX_HIERARCHY_DEPTH} levels.")


# --- use cases --------------------------------------------------------------------------


def create_account(session: Session, principal: Principal, data: AccountCreate) -> Account:
    tenant_id = _tenant(principal)
    if data.owner_id is not None:
        _check_owner(session, principal, data.owner_id)
        owner_id: uuid.UUID | None = data.owner_id
    elif principal.roles & SALES_ROLES:
        owner_id = principal.user_id  # sales staff own what they create
    else:
        owner_id = None
    if data.parent_account_id is not None:
        _check_parent(session, principal, data.parent_account_id, None)
    _check_number(session, tenant_id, data.account_number, None)

    account = Account(
        tenant_id=tenant_id, owner_id=owner_id, **data.model_dump(exclude={"owner_id"})
    )
    session.add(account)
    session.flush()
    _audit(session, principal, account.id, "account.created", diff({}, _snapshot(account)))
    if account.parent_account_id is not None:
        _audit(
            session,
            principal,
            account.parent_account_id,
            "account.child_added",
            {"child_account_id": account.id, "child_name": account.name},
        )
    _flush(session)
    return account


def get_account(session: Session, principal: Principal, account_id: uuid.UUID) -> Account:
    account = repository.get_readable(session, principal, account_id)
    if account is None:
        raise AccountNotFoundError()
    return account


def list_accounts(
    session: Session, principal: Principal, filters: AccountFilters
) -> tuple[Sequence[Account], int]:
    if filters.archived and not principal.has_permission(Permission.ACCOUNT_WRITE_ALL):
        raise ForbiddenError("Only managers and administrators see archived accounts.")
    return repository.search_filtered(session, principal, filters)


def update_account(
    session: Session, principal: Principal, account_id: uuid.UUID, data: AccountUpdate
) -> Account:
    account = _load_for_write(session, principal, account_id)
    _check_version(account, data.version)
    changes = data.changes()
    if "owner_id" in changes and changes["owner_id"] != account.owner_id:
        if not principal.has_permission(Permission.ACCOUNT_WRITE_ALL):
            raise ForbiddenError("Only managers and administrators can change the owner.")
        _check_owner(session, principal, data.owner_id)
    if data.parent_account_id is not None and data.parent_account_id != account.parent_account_id:
        _check_parent(session, principal, data.parent_account_id, account)
    if "account_number" in changes:
        _check_number(session, account.tenant_id, data.account_number, account.id)

    before = _snapshot(account)
    for field, value in changes.items():
        setattr(account, field, value)
    changed = diff(before, _snapshot(account))
    if changed:
        _audit(session, principal, account.id, "account.updated", changed)
    _flush(session)
    return account


def change_status(
    session: Session,
    principal: Principal,
    account_id: uuid.UUID,
    *,
    version: int,
    status: str,
    reason: str | None,
) -> Account:
    account = _load_for_write(session, principal, account_id)
    _check_version(account, version)
    if account.status == status:
        raise AccountStateError(f"The account is already {status}.")
    previous = account.status
    account.status = status
    action = "account.deactivated" if status == "inactive" else "account.activated"
    _audit(
        session,
        principal,
        account.id,
        action,
        {"status": {"old": previous, "new": status}, "reason": reason},
    )
    _flush(session)
    return account


def archive_account(
    session: Session, principal: Principal, account_id: uuid.UUID, *, version: int, reason: str
) -> Account:
    if not principal.has_permission(Permission.ACCOUNT_WRITE_ALL):
        raise ForbiddenError("Only managers and administrators can archive accounts.")
    account = _load_for_write(session, principal, account_id)
    _check_version(account, version)
    if account.status != "inactive":
        raise AccountStateError("Deactivate the account before archiving it.")
    if repository.has_live_children(session, account):
        raise AccountStateError(
            "This account still has child accounts. Move or archive them first."
        )
    account.deleted_at = datetime.now(UTC)
    _audit(session, principal, account.id, "account.archived", {"reason": reason})
    _flush(session)
    return account


def restore_account(
    session: Session, principal: Principal, account_id: uuid.UUID, *, version: int
) -> Account:
    if not principal.has_permission(Permission.ACCOUNT_WRITE_ALL):
        raise ForbiddenError("Only managers and administrators can restore accounts.")
    account = repository.get_archived(session, principal, account_id)
    if account is None:
        raise AccountNotFoundError("Archived account")
    _check_version(account, version)
    if account.parent_account_id is not None:
        parent_archived = session.scalar(
            select(Account.deleted_at).where(
                Account.tenant_id == account.tenant_id, Account.id == account.parent_account_id
            )
        )
        if parent_archived is not None:
            raise AccountStateError("Restore the parent account first.")
    account.deleted_at = None
    _audit(session, principal, account.id, "account.restored", {})
    _flush(session)
    return account


_TITLES = {
    "account.created": "Account created",
    "account.updated": "Details changed",
    "account.activated": "Account reactivated",
    "account.deactivated": "Account deactivated",
    "account.archived": "Account archived",
    "account.restored": "Account restored",
    "account.child_added": "Child account added",
    "account.contact_added": "Contact added",
    "account.contact_removed": "Contact removed",
    "account.primary_contact_changed": "Primary contact changed",
    "account.owner_transferred": "Relationship owner transferred",
}


def account_timeline(
    session: Session, principal: Principal, account_id: uuid.UUID
) -> list[TimelineEntry]:
    account = get_account(session, principal, account_id)
    rows: Sequence[AuditLog] = repository.timeline(session, account)
    people = identity_api.people_by_id(
        session, account.tenant_id, {r.actor_user_id for r in rows if r.actor_user_id}
    )
    return [
        TimelineEntry(
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


def record_account_event(
    session: Session,
    principal: Principal,
    account_id: uuid.UUID,
    action: str,
    changes: dict[str, Any],
) -> None:
    """For other modules (via api.py): note something that happened to an account, e.g. a
    contact being added, so it shows on the account timeline."""
    if action not in _TITLES:
        raise ValueError(f"unknown account event {action!r}")
    _audit(session, principal, account_id, action, changes)


def check_duplicates(
    session: Session,
    principal: Principal,
    *,
    name: str | None,
    website: str | None,
    phone: str | None,
    exclude_id: uuid.UUID | None,
) -> DuplicateCheck:
    """Possible matches before creating or renaming an account.

    The whole organisation is searched (a duplicate owned by a colleague is still a
    duplicate), but only accounts the user may see are named; the rest are just counted.
    """
    tenant_id = _tenant(principal)
    found = repository.duplicate_candidates(
        session, tenant_id, name=name, website=website, phone=phone, exclude_id=exclude_id
    )
    visible_ids = (
        {
            account.id
            for account in session.scalars(
                select(Account).where(
                    Account.id.in_([a.id for a, _ in found]), readable_accounts(principal)
                )
            )
        }
        if found
        else set()
    )
    return DuplicateCheck(
        candidates=[
            DuplicateCandidate(
                id=a.id, name=a.name, city=a.city, country=a.country, reasons=reasons
            )
            for a, reasons in found
            if a.id in visible_ids
        ],
        hidden_matches=sum(1 for a, _ in found if a.id not in visible_ids),
    )


def transfer_owner(
    session: Session,
    principal: Principal,
    account_id: uuid.UUID,
    *,
    version: int,
    new_owner_id: uuid.UUID,
    reason: str,
) -> tuple[Account, uuid.UUID | None]:
    """Hand the customer relationship to another sales employee (managers and admins only).
    Returns the account and its previous owner, so related records can follow."""
    if not principal.has_permission(Permission.ACCOUNT_WRITE_ALL):
        raise ForbiddenError("Only managers and administrators can transfer customers.")
    account = _load_for_write(session, principal, account_id)
    _check_version(account, version)
    if account.owner_id == new_owner_id:
        raise AccountStateError("This person already owns the account.")
    _check_owner(session, principal, new_owner_id)
    previous = account.owner_id
    account.owner_id = new_owner_id
    _audit(
        session,
        principal,
        account.id,
        "account.owner_transferred",
        {"owner_id": {"old": previous, "new": new_owner_id}, "reason": reason},
    )
    _flush(session)
    return account, previous


def readable_summaries(
    session: Session, principal: Principal, *, owner_id: uuid.UUID | None, limit: int
) -> list[Account]:
    """Accounts this user may see (not archived), for the customer-health overview."""
    statement = select(Account).where(readable_accounts(principal))
    if owner_id is not None:
        statement = statement.where(Account.owner_id == owner_id)
    return list(session.scalars(statement.order_by(Account.name, Account.id).limit(limit)))


def set_segment(
    session: Session, principal: Principal, account_id: uuid.UUID, segment: str
) -> None:
    """Used by workflow rules (ADR 0006): same write check and audit as a person's change."""
    if segment not in ACCOUNT_SEGMENTS:
        raise InvalidSegmentError(f"Unknown segment {segment!r}.")
    account = _load_for_write(session, principal, account_id)
    if account.segment == segment:
        return
    _audit(
        session,
        principal,
        account.id,
        "account.updated",
        {"segment": {"old": account.segment, "new": segment}},
    )
    account.segment = segment
    _flush(session)
