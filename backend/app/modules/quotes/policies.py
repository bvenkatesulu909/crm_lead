"""Record-level authorization for quotes.

Staff:
- ``quote:read:all`` / ``quote:write:all`` (tenant admin, sales manager): every quote.
- ``quote:read:own`` / ``quote:write:own`` (sales agent): quotes they own, or on accounts they own.
Customers (portal): only quotes that were SENT to an account in their portal_access_grants
(sent, accepted or declined) - never drafts, approvals or internal notes.
"""

from sqlalchemy import ColumnElement, and_, false, or_

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.modules.accounts.api import owned_account_ids
from app.modules.identity.api import granted_account_ids
from app.modules.quotes.models import Quote
from app.modules.quotes.rules import CUSTOMER_VISIBLE


def _mine(principal: Principal) -> ColumnElement[bool]:
    return or_(
        Quote.owner_id == principal.user_id,
        Quote.account_id.in_(owned_account_ids(principal)),
    )


def readable_quotes(principal: Principal) -> ColumnElement[bool]:
    if principal.tenant_id is None:
        return false()
    in_tenant = Quote.tenant_id == principal.tenant_id
    if principal.user_type == "customer":
        if principal.has_permission(Permission.PORTAL_QUOTE_READ):
            return and_(
                in_tenant,
                Quote.status.in_(CUSTOMER_VISIBLE),
                Quote.account_id.in_(granted_account_ids(principal)),
            )
        return false()
    if principal.user_type != "staff":
        return false()
    if principal.has_permission(Permission.QUOTE_READ_ALL):
        return in_tenant
    if principal.has_permission(Permission.QUOTE_READ_OWN):
        return and_(in_tenant, _mine(principal))
    return false()


def writable_quotes(principal: Principal) -> ColumnElement[bool]:
    if principal.tenant_id is None or principal.user_type != "staff":
        return false()
    in_tenant = Quote.tenant_id == principal.tenant_id
    if principal.has_permission(Permission.QUOTE_WRITE_ALL):
        return in_tenant
    if principal.has_permission(Permission.QUOTE_WRITE_OWN):
        return and_(in_tenant, _mine(principal))
    return false()
