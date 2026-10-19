"""Record-level authorization for leads.

- Only STAFF of the lead's tenant can ever see leads. Customers and platform users: nothing.
- ``lead:read:all`` / ``lead:write:all`` (tenant admin, sales manager): every lead of the tenant.
  (Sales teams don't exist yet, so a manager's "permitted scope" is the whole tenant.)
- ``lead:read:own`` / ``lead:write:own`` (sales agent): only leads they own.
"""

from sqlalchemy import ColumnElement, and_, false

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.modules.leads.models import Lead


def readable_leads(principal: Principal) -> ColumnElement[bool]:
    """SQL condition added to every lead query."""
    if principal.tenant_id is None or principal.user_type != "staff":
        return false()
    in_tenant = and_(Lead.tenant_id == principal.tenant_id, Lead.deleted_at.is_(None))
    if principal.has_permission(Permission.LEAD_READ_ALL):
        return in_tenant
    if principal.has_permission(Permission.LEAD_READ_OWN):
        return and_(in_tenant, Lead.owner_id == principal.user_id)
    return false()


def can_write(principal: Principal, lead: Lead) -> bool:
    """For a lead the principal can already see: may they change it?"""
    if principal.has_permission(Permission.LEAD_WRITE_ALL):
        return True
    return (
        principal.has_permission(Permission.LEAD_WRITE_OWN) and lead.owner_id == principal.user_id
    )
