"""Record-level authorization for tickets.

Staff:
- ``ticket:read:all`` (support agent, tenant admin, sales manager): all tickets of the tenant.
- ``ticket:read:own_accounts`` (sales agent): tickets on customer accounts they own.
- ``ticket:manage`` (support agent, tenant admin): may change tickets they can see.
Customers (portal):
- only tickets on accounts in their portal_access_grants, and only PUBLIC comments.
Nobody ever sees another tenant's tickets.
"""

from sqlalchemy import ColumnElement, and_, false

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.modules.accounts.api import owned_account_ids
from app.modules.identity.api import granted_account_ids
from app.modules.support.models import Ticket


def readable_tickets(principal: Principal) -> ColumnElement[bool]:
    if principal.tenant_id is None:
        return false()
    in_tenant = Ticket.tenant_id == principal.tenant_id
    if principal.user_type == "customer":
        if principal.has_permission(Permission.PORTAL_TICKET_READ):
            return and_(in_tenant, Ticket.account_id.in_(granted_account_ids(principal)))
        return false()
    if principal.user_type != "staff":
        return false()
    if principal.has_permission(Permission.TICKET_READ_ALL):
        return in_tenant
    if principal.has_permission(Permission.TICKET_READ_OWN_ACCOUNTS):
        return and_(in_tenant, Ticket.account_id.in_(owned_account_ids(principal)))
    return false()


def can_manage(principal: Principal) -> bool:
    return principal.user_type == "staff" and principal.has_permission(Permission.TICKET_MANAGE)
