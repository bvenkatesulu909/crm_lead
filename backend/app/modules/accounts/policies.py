"""Record-level authorization for accounts: WHICH account rows a principal may read.

The result is a SQL condition that is added to every query, so filtering happens inside the
database. Unauthorized rows are never loaded, list counts stay correct, and a request for an
account the user may not see looks exactly like a request for one that does not exist (404).
"""

from sqlalchemy import ColumnElement, and_, false

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.modules.accounts.models import Account
from app.modules.identity.api import granted_account_ids


def readable_accounts(principal: Principal) -> ColumnElement[bool]:
    if principal.tenant_id is None:
        # Platform users (super admins) have no tenant and therefore see no tenant data.
        return false()

    # Tenant-level rule: always, for everyone.
    in_tenant = and_(Account.tenant_id == principal.tenant_id, Account.deleted_at.is_(None))

    # Record-level rules, from the widest permission the principal holds.
    if principal.user_type == "customer":
        if principal.has_permission(Permission.PORTAL_ACCOUNT_READ):
            return and_(in_tenant, Account.id.in_(granted_account_ids(principal)))
        return false()
    if principal.has_permission(Permission.ACCOUNT_READ_ALL):
        return in_tenant
    if principal.has_permission(Permission.ACCOUNT_READ_OWN):
        return and_(in_tenant, Account.owner_id == principal.user_id)
    return false()


def can_write(principal: Principal, account: Account) -> bool:
    """For an account the principal can already see: may they change it?"""
    if principal.user_type != "staff":
        return False
    if principal.has_permission(Permission.ACCOUNT_WRITE_ALL):
        return True
    return (
        principal.has_permission(Permission.ACCOUNT_WRITE_OWN)
        and account.owner_id == principal.user_id
    )


def archived_accounts(principal: Principal) -> ColumnElement[bool]:
    """Archived accounts are visible only to staff who may change every account (to restore)."""
    if (
        principal.tenant_id is None
        or principal.user_type != "staff"
        or not principal.has_permission(Permission.ACCOUNT_WRITE_ALL)
    ):
        return false()
    return and_(Account.tenant_id == principal.tenant_id, Account.deleted_at.is_not(None))
