"""Record-level authorization for orders.

Staff:
- ``order:read:all`` (tenant admin, sales manager, support agent): every order of the tenant.
- ``order:read:own_accounts`` (sales agent): orders on customer accounts they own.
- ``order:write:all`` / ``order:write:own_accounts``: create orders, edit drafts, confirm and
  cancel - on all accounts, or only on accounts they own.
- ``order:fulfil`` (tenant admin, sales manager): in fulfilment / shipped / delivered, and
  cancelling an order that is already being prepared.
Customers (portal):
- only orders on accounts in their portal_access_grants, and NEVER drafts.
Nobody ever sees another tenant's orders.
"""

from sqlalchemy import ColumnElement, and_, false

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.modules.accounts.api import owned_account_ids
from app.modules.identity.api import granted_account_ids
from app.modules.orders.models import Order


def readable_orders(principal: Principal) -> ColumnElement[bool]:
    if principal.tenant_id is None:
        return false()
    in_tenant = Order.tenant_id == principal.tenant_id
    if principal.user_type == "customer":
        if principal.has_permission(Permission.PORTAL_ORDER_READ):
            return and_(
                in_tenant,
                Order.status != "draft",
                Order.account_id.in_(granted_account_ids(principal)),
            )
        return false()
    if principal.user_type != "staff":
        return false()
    if principal.has_permission(Permission.ORDER_READ_ALL):
        return in_tenant
    if principal.has_permission(Permission.ORDER_READ_OWN_ACCOUNTS):
        return and_(in_tenant, Order.account_id.in_(owned_account_ids(principal)))
    return false()


def writable_orders(principal: Principal) -> ColumnElement[bool]:
    if principal.tenant_id is None or principal.user_type != "staff":
        return false()
    in_tenant = Order.tenant_id == principal.tenant_id
    if principal.has_permission(Permission.ORDER_WRITE_ALL):
        return in_tenant
    if principal.has_permission(Permission.ORDER_WRITE_OWN_ACCOUNTS):
        return and_(in_tenant, Order.account_id.in_(owned_account_ids(principal)))
    return false()


def can_write_any(principal: Principal) -> bool:
    return principal.user_type == "staff" and (
        principal.has_permission(Permission.ORDER_WRITE_ALL)
        or principal.has_permission(Permission.ORDER_WRITE_OWN_ACCOUNTS)
    )


def can_fulfil(principal: Principal) -> bool:
    return principal.user_type == "staff" and principal.has_permission(Permission.ORDER_FULFIL)
