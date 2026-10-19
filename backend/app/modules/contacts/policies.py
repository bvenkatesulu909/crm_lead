"""Record-level authorization for contacts.

- Only STAFF of the contact's tenant see contacts (the portal has no contact screens).
- ``contact:read:all`` (admins, managers, support): every contact of the tenant.
- ``contact:read:own`` (sales agents): contacts they own, plus every contact of an account they
  own - the people at "my" customers.
Writing follows the same shape with the ``contact:write:*`` permissions.
"""

from sqlalchemy import ColumnElement, and_, false, or_

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.modules.accounts import api as accounts_api
from app.modules.contacts.models import Contact


def mine(principal: Principal) -> ColumnElement[bool]:
    return or_(
        Contact.owner_id == principal.user_id,
        Contact.account_id.in_(accounts_api.owned_account_ids(principal)),
    )


def readable_contacts(principal: Principal) -> ColumnElement[bool]:
    """SQL condition added to every contact query."""
    if principal.tenant_id is None or principal.user_type != "staff":
        return false()
    in_tenant = and_(Contact.tenant_id == principal.tenant_id, Contact.deleted_at.is_(None))
    if principal.has_permission(Permission.CONTACT_READ_ALL):
        return in_tenant
    if principal.has_permission(Permission.CONTACT_READ_OWN):
        return and_(in_tenant, mine(principal))
    return false()


def writable_contacts(principal: Principal) -> ColumnElement[bool]:
    """SQL condition: contacts the principal may change."""
    if principal.tenant_id is None or principal.user_type != "staff":
        return false()
    in_tenant = and_(Contact.tenant_id == principal.tenant_id, Contact.deleted_at.is_(None))
    if principal.has_permission(Permission.CONTACT_WRITE_ALL):
        return in_tenant
    if principal.has_permission(Permission.CONTACT_WRITE_OWN):
        return and_(in_tenant, mine(principal))
    return false()
