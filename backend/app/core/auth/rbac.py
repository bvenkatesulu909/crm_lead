"""Roles, permissions and the role -> permission matrix (RBAC).

Roles are assigned in Keycloak and arrive in the access token. Permissions are decided HERE,
in reviewed and tested code: a role name in a token can never grant more than this table says.

Permission names are ``resource:action[:scope]``. Scope ``own`` means "records I own",
``all`` means "all records of my tenant". No permission ever crosses tenants.
"""

from enum import StrEnum


class Role(StrEnum):
    SUPER_ADMIN = "super_admin"
    TENANT_ADMIN = "tenant_admin"
    SALES_MANAGER = "sales_manager"
    SALES_AGENT = "sales_agent"
    SUPPORT_AGENT = "support_agent"
    CUSTOMER = "customer"


class Permission(StrEnum):
    PLATFORM_TENANT_READ = "platform:tenant:read"
    PLATFORM_TENANT_MANAGE = "platform:tenant:manage"

    TENANT_USER_READ = "tenant:user:read"
    TENANT_USER_MANAGE = "tenant:user:manage"
    # Invite customer contacts to the portal for an account (ADR 0004). Record-level:
    # tenant admins for any account, sales agents only for accounts they own.
    PORTAL_USER_INVITE = "portal:user:invite"

    ACCOUNT_READ_ALL = "account:read:all"
    ACCOUNT_READ_OWN = "account:read:own"
    ACCOUNT_WRITE_ALL = "account:write:all"
    ACCOUNT_WRITE_OWN = "account:write:own"

    CONTACT_READ_ALL = "contact:read:all"
    CONTACT_READ_OWN = "contact:read:own"
    CONTACT_WRITE_ALL = "contact:write:all"
    CONTACT_WRITE_OWN = "contact:write:own"

    LEAD_READ_ALL = "lead:read:all"
    LEAD_READ_OWN = "lead:read:own"
    LEAD_WRITE_ALL = "lead:write:all"
    LEAD_WRITE_OWN = "lead:write:own"
    # Give a lead to another sales employee (changes who may see it).
    LEAD_ASSIGN = "lead:assign"
    # Turn a qualified lead into account + contact (+ opportunity). Still limited by write scope.
    LEAD_CONVERT = "lead:convert"

    # Support tickets (staff side).
    TICKET_READ_ALL = "ticket:read:all"
    # Tickets on customer accounts the user owns (sales agents follow their customers).
    TICKET_READ_OWN_ACCOUNTS = "ticket:read:own_accounts"
    # Create, assign, change status/priority, comment.
    TICKET_MANAGE = "ticket:manage"

    # Orders (staff side).
    ORDER_READ_ALL = "order:read:all"
    ORDER_READ_OWN_ACCOUNTS = "order:read:own_accounts"
    # Create orders, edit drafts, confirm, cancel.
    ORDER_WRITE_ALL = "order:write:all"
    ORDER_WRITE_OWN_ACCOUNTS = "order:write:own_accounts"
    # Move confirmed orders through fulfilment: in fulfilment, shipped, delivered.
    ORDER_FULFIL = "order:fulfil"

    # Invoices (staff side).
    INVOICE_READ_ALL = "invoice:read:all"
    INVOICE_READ_OWN_ACCOUNTS = "invoice:read:own_accounts"
    # Create invoices from orders, issue or discard drafts, issue credit notes.
    INVOICE_MANAGE = "invoice:manage"
    # Record received payments and reverse mistaken ones.
    PAYMENT_RECORD = "payment:record"

    # Customer portal: only accounts listed in the user's portal_access_grants.
    PORTAL_ACCOUNT_READ = "portal:account:read"
    # Customer portal tickets: only on granted accounts, public comments only.
    PORTAL_TICKET_READ = "portal:ticket:read"
    PORTAL_TICKET_WRITE = "portal:ticket:write"
    # Customer portal orders: confirmed (non-draft) orders of granted accounts only.
    PORTAL_ORDER_READ = "portal:order:read"
    # Customer portal invoices: issued invoices of granted accounts only.
    PORTAL_INVOICE_READ = "portal:invoice:read"
    # Customer portal AI assistant (ADR 0003): chat that can only read the customer's own data.
    PORTAL_ASSISTANT_USE = "portal:assistant:use"

    # Opportunities (deals in the sales pipeline). "own" = opportunities the user owns.
    OPPORTUNITY_READ_ALL = "opportunity:read:all"
    OPPORTUNITY_READ_OWN = "opportunity:read:own"
    OPPORTUNITY_WRITE_ALL = "opportunity:write:all"
    OPPORTUNITY_WRITE_OWN = "opportunity:write:own"

    # Activities and tasks (calls, meetings, e-mails, notes, to-dos). "own" = assigned to or
    # created by the user, or linked to a record the user owns. "assign" = give tasks to others.
    ACTIVITY_READ_ALL = "activity:read:all"
    ACTIVITY_READ_OWN = "activity:read:own"
    ACTIVITY_WRITE_ALL = "activity:write:all"
    ACTIVITY_WRITE_OWN = "activity:write:own"
    ACTIVITY_ASSIGN = "activity:assign"

    # Product catalogue and price books: everyone in sales/support reads them, managers maintain
    # them (prices are governed - sales reps cannot invent their own).
    CATALOG_READ = "catalog:read"
    CATALOG_MANAGE = "catalog:manage"

    # Quotes. "own" = quotes the user owns or on accounts the user owns. "approve" = release
    # quotes with discounts above the limit (never one's own, except tenant admins).
    QUOTE_READ_ALL = "quote:read:all"
    QUOTE_READ_OWN = "quote:read:own"
    QUOTE_WRITE_ALL = "quote:write:all"
    QUOTE_WRITE_OWN = "quote:write:own"
    QUOTE_APPROVE = "quote:approve"
    # Organisation settings for quotes (e.g. the discount that needs approval).
    QUOTE_SETTINGS_MANAGE = "quote:settings:manage"
    # Customer portal: see quotes sent to their company and accept or decline them.
    PORTAL_QUOTE_READ = "portal:quote:read"
    PORTAL_QUOTE_RESPOND = "portal:quote:respond"
    # Documents on accounts and deals (Phase 10). Access to a document also needs access to
    # the record it belongs to.
    DOCUMENT_READ = "document:read"
    DOCUMENT_WRITE = "document:write"
    DOCUMENT_DELETE = "document:delete"
    PORTAL_DOCUMENT_READ = "portal:document:read"
    # Everyone on the staff side reads their own notifications (ADR 0006).
    NOTIFICATION_READ = "notification:read"
    # Tenant admins define workflow rules (ADR 0006, step 17b).
    WORKFLOW_MANAGE = "workflow:manage"

    # Dashboards: sales figures for the whole organisation, for one's own records, and the
    # executive view (sales + revenue + support).
    DASHBOARD_SALES_ALL = "dashboard:sales:all"
    DASHBOARD_SALES_OWN = "dashboard:sales:own"
    DASHBOARD_EXECUTIVE = "dashboard:executive"


_P = Permission

_SALES_ALL = frozenset(
    {
        _P.ACCOUNT_READ_ALL, _P.ACCOUNT_WRITE_ALL,
        _P.CONTACT_READ_ALL, _P.CONTACT_WRITE_ALL,
        _P.LEAD_READ_ALL, _P.LEAD_WRITE_ALL, _P.LEAD_ASSIGN, _P.LEAD_CONVERT,
        _P.OPPORTUNITY_READ_ALL, _P.OPPORTUNITY_WRITE_ALL, _P.DASHBOARD_SALES_ALL,
        _P.ACTIVITY_READ_ALL, _P.ACTIVITY_WRITE_ALL, _P.ACTIVITY_ASSIGN,
        _P.CATALOG_READ, _P.CATALOG_MANAGE,
        _P.QUOTE_READ_ALL, _P.QUOTE_WRITE_ALL, _P.QUOTE_APPROVE,
        _P.DOCUMENT_READ, _P.DOCUMENT_WRITE, _P.DOCUMENT_DELETE,
    }
)  # fmt: skip

_ORDERS_ALL = frozenset({_P.ORDER_READ_ALL, _P.ORDER_WRITE_ALL, _P.ORDER_FULFIL})
_BILLING_ALL = frozenset({_P.INVOICE_READ_ALL, _P.INVOICE_MANAGE, _P.PAYMENT_RECORD})

_STAFF_BASICS = frozenset({_P.NOTIFICATION_READ})

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    # Platform operator: manages tenants, but sees NO tenant business data.
    Role.SUPER_ADMIN: frozenset({_P.PLATFORM_TENANT_READ, _P.PLATFORM_TENANT_MANAGE}),
    Role.TENANT_ADMIN: _SALES_ALL
    | {_P.TENANT_USER_READ, _P.TENANT_USER_MANAGE, _P.PORTAL_USER_INVITE}
    | {_P.QUOTE_SETTINGS_MANAGE}
    | {_P.TICKET_READ_ALL, _P.TICKET_MANAGE}
    | _ORDERS_ALL
    | _BILLING_ALL
    | {_P.DASHBOARD_EXECUTIVE, _P.WORKFLOW_MANAGE}
    | _STAFF_BASICS,
    Role.SALES_MANAGER: _SALES_ALL
    | {_P.TICKET_READ_ALL}
    | _ORDERS_ALL
    | _BILLING_ALL
    | _STAFF_BASICS,
    Role.SALES_AGENT: frozenset(
        {
            _P.ACCOUNT_READ_OWN,
            _P.ACCOUNT_WRITE_OWN,
            _P.CONTACT_READ_OWN,
            _P.CONTACT_WRITE_OWN,
            _P.LEAD_READ_OWN,
            _P.LEAD_WRITE_OWN,
            _P.LEAD_CONVERT,
            _P.OPPORTUNITY_READ_OWN,
            _P.OPPORTUNITY_WRITE_OWN,
            _P.ACTIVITY_READ_OWN,
            _P.ACTIVITY_WRITE_OWN,
            _P.CATALOG_READ,
            _P.QUOTE_READ_OWN,
            _P.QUOTE_WRITE_OWN,
            _P.DOCUMENT_READ,
            _P.DOCUMENT_WRITE,
            _P.DASHBOARD_SALES_OWN,
            _P.TICKET_READ_OWN_ACCOUNTS,
            _P.ORDER_READ_OWN_ACCOUNTS,
            _P.ORDER_WRITE_OWN_ACCOUNTS,
            _P.INVOICE_READ_OWN_ACCOUNTS,
            _P.PORTAL_USER_INVITE,
            _P.NOTIFICATION_READ,
        }
    ),  # fmt: skip
    Role.SUPPORT_AGENT: frozenset(
        {
            _P.ACCOUNT_READ_ALL,
            _P.CONTACT_READ_ALL,
            _P.TICKET_READ_ALL,
            _P.TICKET_MANAGE,
            _P.ORDER_READ_ALL,
            _P.INVOICE_READ_ALL,
            _P.ACTIVITY_READ_OWN,
            _P.ACTIVITY_WRITE_OWN,
            _P.CATALOG_READ,
            _P.DOCUMENT_READ,
            _P.NOTIFICATION_READ,
        }
    ),
    Role.CUSTOMER: frozenset(
        {
            _P.PORTAL_ACCOUNT_READ,
            _P.PORTAL_TICKET_READ,
            _P.PORTAL_TICKET_WRITE,
            _P.PORTAL_ORDER_READ,
            _P.PORTAL_INVOICE_READ,
            _P.PORTAL_ASSISTANT_USE,
            _P.PORTAL_QUOTE_READ,
            _P.PORTAL_QUOTE_RESPOND,
            _P.PORTAL_DOCUMENT_READ,
        }
    ),
}

# Which roles are meaningful for which kind of user. Roles outside the user's group are
# ignored even if Keycloak puts them in the token (defence in depth against misconfiguration).
PLATFORM_ROLES = frozenset({Role.SUPER_ADMIN})
STAFF_ROLES = frozenset(
    {Role.TENANT_ADMIN, Role.SALES_MANAGER, Role.SALES_AGENT, Role.SUPPORT_AGENT}
)
CUSTOMER_ROLES = frozenset({Role.CUSTOMER})


def parse_roles(names: frozenset[str]) -> frozenset[Role]:
    """Keep only role names the CRM knows; unknown names (e.g. Keycloak defaults) are ignored."""
    known = {role.value for role in Role}
    return frozenset(Role(name) for name in names if name in known)


def permissions_for(roles: frozenset[Role]) -> frozenset[Permission]:
    granted: set[Permission] = set()
    for role in roles:
        granted |= ROLE_PERMISSIONS[role]
    return frozenset(granted)


# Users who may own leads ("sales employees"). Checked against the role snapshot stored on the
# CRM user (refreshed at every sign-in) when a lead is assigned to someone else.
SALES_ROLES = frozenset({Role.SALES_AGENT, Role.SALES_MANAGER})

# Users who may be assigned support tickets.
SUPPORT_ROLES = frozenset({Role.SUPPORT_AGENT, Role.TENANT_ADMIN})


# What the per-tenant "Automation" identity may do when a workflow rule acts (ADR 0006). Not a
# role: nobody can sign in as automation, and it never acts outside its own tenant.
AUTOMATION_PERMISSIONS = frozenset(
    {
        _P.LEAD_READ_ALL, _P.LEAD_WRITE_ALL,
        _P.ACCOUNT_READ_ALL, _P.ACCOUNT_WRITE_ALL,
        _P.CONTACT_READ_ALL,
        _P.OPPORTUNITY_READ_ALL,
        _P.ACTIVITY_READ_ALL, _P.ACTIVITY_WRITE_ALL, _P.ACTIVITY_ASSIGN,
        _P.QUOTE_READ_ALL,
        _P.TICKET_READ_ALL,
        _P.ORDER_READ_ALL,
    }
)  # fmt: skip
