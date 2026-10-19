"""Record-level authorization for invoices (credit notes and payments follow their invoice).

Staff:
- ``invoice:read:all`` (tenant admin, sales manager, support agent): every invoice of the tenant.
- ``invoice:read:own_accounts`` (sales agent): invoices on customer accounts they own.
- ``invoice:manage`` / ``payment:record`` (tenant admin, sales manager): change them.
Customers (portal):
- only ISSUED invoices on accounts in their portal_access_grants (never drafts or discarded).
Nobody ever sees another tenant's invoices.
"""

from sqlalchemy import ColumnElement, and_, false

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.modules.accounts.api import owned_account_ids
from app.modules.identity.api import granted_account_ids
from app.modules.invoices.models import Invoice


def readable_invoices(principal: Principal) -> ColumnElement[bool]:
    if principal.tenant_id is None:
        return false()
    in_tenant = Invoice.tenant_id == principal.tenant_id
    if principal.user_type == "customer":
        if principal.has_permission(Permission.PORTAL_INVOICE_READ):
            return and_(
                in_tenant,
                Invoice.status == "issued",
                Invoice.account_id.in_(granted_account_ids(principal)),
            )
        return false()
    if principal.user_type != "staff":
        return false()
    if principal.has_permission(Permission.INVOICE_READ_ALL):
        return in_tenant
    if principal.has_permission(Permission.INVOICE_READ_OWN_ACCOUNTS):
        return and_(in_tenant, Invoice.account_id.in_(owned_account_ids(principal)))
    return false()


def can_manage(principal: Principal) -> bool:
    return principal.user_type == "staff" and principal.has_permission(Permission.INVOICE_MANAGE)


def can_record_payments(principal: Principal) -> bool:
    return principal.user_type == "staff" and principal.has_permission(Permission.PAYMENT_RECORD)
