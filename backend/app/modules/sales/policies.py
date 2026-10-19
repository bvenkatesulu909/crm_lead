"""Record-level authorization for opportunities.

- ``opportunity:read:all`` (tenant admin, sales manager): every opportunity of the tenant.
- ``opportunity:read:own`` (sales agent): opportunities they own.
Customers, support and platform users: none.
"""

from sqlalchemy import ColumnElement, and_, false

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.modules.sales.models import Opportunity


def readable_opportunities(principal: Principal) -> ColumnElement[bool]:
    if principal.tenant_id is None or principal.user_type != "staff":
        return false()
    in_tenant = and_(Opportunity.tenant_id == principal.tenant_id, Opportunity.deleted_at.is_(None))
    if principal.has_permission(Permission.OPPORTUNITY_READ_ALL):
        return in_tenant
    if principal.has_permission(Permission.OPPORTUNITY_READ_OWN):
        return and_(in_tenant, Opportunity.owner_id == principal.user_id)
    return false()


def can_write(principal: Principal, opportunity: Opportunity) -> bool:
    """For an opportunity the principal can already see: may they change it?"""
    if principal.user_type != "staff":
        return False
    if principal.has_permission(Permission.OPPORTUNITY_WRITE_ALL):
        return True
    return (
        principal.has_permission(Permission.OPPORTUNITY_WRITE_OWN)
        and opportunity.owner_id == principal.user_id
    )
