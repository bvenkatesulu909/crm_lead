"""Record-level authorization for e-mail messages (ADR 0012).

Staff only:
- ``communication:read:all`` (tenant admin, sales manager): every message of the tenant.
- ``communication:read:own`` (sales and support agents): messages they sent or logged.
A record's own history (step CC4) follows that record's read rules instead. A message the
user may not see is a 404, never a 403.
"""

from sqlalchemy import ColumnElement, and_, false

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.modules.communications.models import EmailMessage


def readable_messages(principal: Principal) -> ColumnElement[bool]:
    if principal.tenant_id is None or principal.user_type != "staff":
        return false()
    in_tenant = EmailMessage.tenant_id == principal.tenant_id
    if principal.has_permission(Permission.COMMUNICATION_READ_ALL):
        return in_tenant
    if principal.has_permission(Permission.COMMUNICATION_READ_OWN):
        return and_(in_tenant, EmailMessage.sent_by_user_id == principal.user_id)
    return false()
