"""Saved filters (ADR 0042, BR-pre): create, list, change, delete.

A filter is private to its owner until the owner shares it with the organisation. Only people who
may change every account (managers, administrators) can share. Only the owner changes a filter; a
tenant administrator may also delete or unshare a shared one. The service never commits.
"""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission, Role
from app.core.errors import ConflictError, DomainError, ForbiddenError, NotFoundError
from app.modules.saved_filters import repository, rules
from app.modules.saved_filters.models import SavedFilter

ENTITY = "saved_filter"


class SavedFilterNotFoundError(NotFoundError):
    code = "saved_filter_not_found"

    def __init__(self) -> None:
        # The same answer for a missing filter and for someone else's private one.
        super().__init__("There is no such saved filter.")


class InvalidSavedFilterError(DomainError):
    status_code = 422
    code = "invalid_saved_filter"


class NameTakenError(ConflictError):
    code = "saved_filter_name_taken"

    def __init__(self) -> None:
        super().__init__("You already have a filter with this name (or the shared one has it).")


class TooManyFiltersError(ConflictError):
    code = "saved_filter_limit"


class VersionConflictError(ConflictError):
    code = "version_conflict"

    def __init__(self) -> None:
        super().__init__("The filter was changed by someone else. Reload it and try again.")


def _ids(principal: Principal) -> tuple[uuid.UUID, uuid.UUID]:
    if principal.tenant_id is None or principal.user_id is None:
        raise ForbiddenError("Saved filters belong to people in an organisation.")
    return principal.tenant_id, principal.user_id


def _may_read_accounts(principal: Principal) -> None:
    if not principal.permissions & {Permission.ACCOUNT_READ_ALL, Permission.ACCOUNT_READ_OWN}:
        raise ForbiddenError("You may not read accounts.")


def _check_share(principal: Principal, shared: bool) -> None:
    if shared and not principal.has_permission(Permission.ACCOUNT_WRITE_ALL):
        raise ForbiddenError("Only managers and administrators can share a filter.")


def list_filters(
    session: Session, principal: Principal, record_type: str = "account"
) -> list[SavedFilter]:
    _may_read_accounts(principal)
    tenant_id, user_id = _ids(principal)
    return repository.list_visible(session, tenant_id, user_id, record_type)


def get_filter(session: Session, principal: Principal, filter_id: uuid.UUID) -> SavedFilter:
    _may_read_accounts(principal)
    tenant_id, user_id = _ids(principal)
    found = repository.get_visible(session, tenant_id, user_id, filter_id)
    if found is None:
        raise SavedFilterNotFoundError
    return found


def create_filter(
    session: Session,
    principal: Principal,
    *,
    name: str,
    params: dict[str, Any],
    shared: bool = False,
    record_type: str = "account",
) -> SavedFilter:
    _may_read_accounts(principal)
    tenant_id, user_id = _ids(principal)
    _check_share(principal, shared)
    try:
        clean = rules.clean_name(name)
        cleaned = rules.clean_params(record_type, params)
    except rules.InvalidFilterError as exc:
        raise InvalidSavedFilterError(str(exc)) from None
    if repository.count_own(session, tenant_id, user_id) >= rules.MAX_PER_PERSON:
        raise TooManyFiltersError(f"You can keep at most {rules.MAX_PER_PERSON} saved filters.")
    if shared and repository.count_shared(session, tenant_id) >= rules.MAX_SHARED:
        raise TooManyFiltersError(f"An organisation can share at most {rules.MAX_SHARED} filters.")
    if repository.name_taken(session, tenant_id, user_id, clean, shared=False) or (
        shared and repository.name_taken(session, tenant_id, user_id, clean, shared=True)
    ):
        raise NameTakenError
    item = SavedFilter(
        tenant_id=tenant_id,
        owner_user_id=user_id,
        record_type=record_type,
        name=clean,
        params=cleaned,
        shared=shared,
    )
    session.add(item)
    session.flush()
    record_audit(
        session,
        principal,
        action="saved_filter.created",
        entity_type=ENTITY,
        entity_id=item.id,
        changes={"record_type": record_type, "shared": shared, "keys": sorted(cleaned)},
    )
    return item


def _load_for_change(
    session: Session, principal: Principal, filter_id: uuid.UUID, *, allow_admin: bool
) -> SavedFilter:
    item = get_filter(session, principal, filter_id)
    _, user_id = _ids(principal)
    if item.owner_user_id == user_id:
        return item
    admin = principal.roles & {Role.TENANT_ADMIN}
    if allow_admin and admin and item.shared:
        return item
    # Someone else's shared filter may be used by everybody but changed only by its owner.
    raise ForbiddenError("Only the owner can change this filter.")


def update_filter(
    session: Session,
    principal: Principal,
    filter_id: uuid.UUID,
    *,
    version: int,
    name: str | None = None,
    params: dict[str, Any] | None = None,
    shared: bool | None = None,
) -> SavedFilter:
    tenant_id, user_id = _ids(principal)
    # A tenant administrator may unshare someone else's shared filter, nothing more.
    item = _load_for_change(session, principal, filter_id, allow_admin=True)
    owner_change = item.owner_user_id == user_id
    if not owner_change and (name is not None or params is not None or shared is not False):
        raise ForbiddenError("An administrator can only stop sharing someone else's filter.")
    if item.version != version:
        raise VersionConflictError
    if shared:
        _check_share(principal, True)
    try:
        new_name = rules.clean_name(name) if name is not None else item.name
        new_params = (
            rules.clean_params(item.record_type, params) if params is not None else item.params
        )
    except rules.InvalidFilterError as exc:
        raise InvalidSavedFilterError(str(exc)) from None
    new_shared = item.shared if shared is None else shared
    if new_shared and not item.shared:
        if repository.count_shared(session, tenant_id) >= rules.MAX_SHARED:
            raise TooManyFiltersError(
                f"An organisation can share at most {rules.MAX_SHARED} filters."
            )
    if repository.name_taken(
        session, tenant_id, item.owner_user_id, new_name, shared=False, except_id=item.id
    ) or (
        new_shared
        and repository.name_taken(
            session, tenant_id, item.owner_user_id, new_name, shared=True, except_id=item.id
        )
    ):
        raise NameTakenError
    changed = [
        field
        for field, before, after in (
            ("name", item.name, new_name),
            ("params", item.params, new_params),
            ("shared", item.shared, new_shared),
        )
        if before != after
    ]
    if not changed:
        raise InvalidSavedFilterError("Nothing was changed.")
    item.name, item.params, item.shared = new_name, new_params, new_shared
    session.flush()
    record_audit(
        session,
        principal,
        action="saved_filter.updated",
        entity_type=ENTITY,
        entity_id=item.id,
        changes={"fields": changed},
    )
    return item


def delete_filter(session: Session, principal: Principal, filter_id: uuid.UUID) -> None:
    item = _load_for_change(session, principal, filter_id, allow_admin=True)
    session.delete(item)
    session.flush()
    record_audit(
        session,
        principal,
        action="saved_filter.deleted",
        entity_type=ENTITY,
        entity_id=filter_id,
        changes={"shared": item.shared},
    )
