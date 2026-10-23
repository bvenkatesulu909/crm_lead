"""Record-level authorization for contracts.

Staff only (customers get a portal view later):
- ``contract:read:all`` / ``contract:write:all`` (tenant admin, sales manager): every contract.
- ``contract:read:own`` / ``contract:write:own`` (sales agent): contracts they own, or on
  accounts they own.
Support agents and customers get nothing: a contract they may not see is a 404, never a 403.
"""

from sqlalchemy import ColumnElement, and_, false, or_

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.modules.accounts.api import owned_account_ids
from app.modules.contracts.models import Contract


def _mine(principal: Principal) -> ColumnElement[bool]:
    return or_(
        Contract.owner_id == principal.user_id,
        Contract.account_id.in_(owned_account_ids(principal)),
    )


def readable_contracts(principal: Principal) -> ColumnElement[bool]:
    if principal.tenant_id is None or principal.user_type != "staff":
        return false()
    in_tenant = Contract.tenant_id == principal.tenant_id
    if principal.has_permission(Permission.CONTRACT_READ_ALL):
        return in_tenant
    if principal.has_permission(Permission.CONTRACT_READ_OWN):
        return and_(in_tenant, _mine(principal))
    return false()


def writable_contracts(principal: Principal) -> ColumnElement[bool]:
    if principal.tenant_id is None or principal.user_type != "staff":
        return false()
    in_tenant = Contract.tenant_id == principal.tenant_id
    if principal.has_permission(Permission.CONTRACT_WRITE_ALL):
        return in_tenant
    if principal.has_permission(Permission.CONTRACT_WRITE_OWN):
        return and_(in_tenant, _mine(principal))
    return false()
