"""Record-level authorization for activities and tasks.

- Only STAFF of the tenant; customers never see internal activities.
- ``activity:read:all`` / ``write:all`` (admins, sales managers): every activity of the tenant.
- ``activity:read:own`` / ``write:own`` (sales agents, support): activities assigned to them or
  created by them, plus activities linked to a lead, account, contact or opportunity they own.
"""

from sqlalchemy import ColumnElement, and_, false, or_

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.modules.accounts import api as accounts_api
from app.modules.activities.models import Activity
from app.modules.contacts import api as contacts_api
from app.modules.leads import api as leads_api
from app.modules.sales import api as sales_api


def _mine(principal: Principal) -> ColumnElement[bool]:
    return or_(
        Activity.assignee_id == principal.user_id,
        Activity.created_by_user_id == principal.user_id,
        Activity.lead_id.in_(leads_api.owned_lead_ids(principal)),
        Activity.account_id.in_(accounts_api.owned_account_ids(principal)),
        Activity.contact_id.in_(contacts_api.mine_contact_ids(principal)),
        Activity.opportunity_id.in_(sales_api.owned_opportunity_ids(principal)),
    )


def _scope(principal: Principal, every: Permission, own: Permission) -> ColumnElement[bool]:
    if principal.tenant_id is None or principal.user_type != "staff":
        return false()
    in_tenant = Activity.tenant_id == principal.tenant_id
    if principal.has_permission(every):
        return in_tenant
    if principal.has_permission(own):
        return and_(in_tenant, _mine(principal))
    return false()


def readable_activities(principal: Principal) -> ColumnElement[bool]:
    return _scope(principal, Permission.ACTIVITY_READ_ALL, Permission.ACTIVITY_READ_OWN)


def writable_activities(principal: Principal) -> ColumnElement[bool]:
    return _scope(principal, Permission.ACTIVITY_WRITE_ALL, Permission.ACTIVITY_WRITE_OWN)
