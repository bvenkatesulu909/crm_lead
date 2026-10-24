import type { Me } from "@/lib/api-types";

/**
 * UI visibility only. The backend enforces every permission again on every request, so a
 * hidden link is a convenience, never the protection.
 */
export function hasAny(
  me: Pick<Me, "permissions">,
  ...permissions: string[]
): boolean {
  return permissions.some((p) => me.permissions.includes(p));
}

export const canReadLeads = (me: Pick<Me, "permissions">) =>
  hasAny(me, "lead:read:all", "lead:read:own");
export const canWriteLeads = (me: Pick<Me, "permissions">) =>
  hasAny(me, "lead:write:all", "lead:write:own");

export const canReadAccounts = (me: Pick<Me, "permissions">) =>
  hasAny(me, "account:read:all", "account:read:own");

export const canWriteAccounts = (me: Pick<Me, "permissions">) =>
  hasAny(me, "account:write:all", "account:write:own");
/** Archive/restore, change owners, see archived accounts. */
export const canManageAccounts = (me: Pick<Me, "permissions">) =>
  hasAny(me, "account:write:all");

export const canReadContacts = (me: Pick<Me, "permissions">) =>
  hasAny(me, "contact:read:all", "contact:read:own");
export const canWriteContacts = (me: Pick<Me, "permissions">) =>
  hasAny(me, "contact:write:all", "contact:write:own");
export const canManageContacts = (me: Pick<Me, "permissions">) =>
  hasAny(me, "contact:write:all");

export const canReadOpportunities = (me: Pick<Me, "permissions">) =>
  hasAny(me, "opportunity:read:all", "opportunity:read:own");
export const canWriteOpportunities = (me: Pick<Me, "permissions">) =>
  hasAny(me, "opportunity:write:all", "opportunity:write:own");
/** Reopen closed deals, change deal owners. */
export const canManageOpportunities = (me: Pick<Me, "permissions">) =>
  hasAny(me, "opportunity:write:all");

export const canReadCatalog = (me: Pick<Me, "permissions">) =>
  hasAny(me, "catalog:read");
export const canManageCatalog = (me: Pick<Me, "permissions">) =>
  hasAny(me, "catalog:manage");
export const canManageWorkflows = (me: Pick<Me, "permissions">) =>
  hasAny(me, "workflow:manage");
/** Staff with access to any sales, quote, invoice, order, ticket or contact data. */
export const canUseReports = (me: Pick<Me, "permissions">) =>
  hasAny(
    me,
    "dashboard:sales:all",
    "dashboard:sales:own",
    "quote:read:all",
    "quote:read:own",
    "invoice:read:all",
    "invoice:read:own_accounts",
    "order:read:all",
    "order:read:own_accounts",
    "ticket:read:all",
    "ticket:read:own_accounts",
    "account:read:all",
    "account:read:own",
  );
export const canReadNotifications = (me: Pick<Me, "permissions">) =>
  hasAny(me, "notification:read");
export const canReadDocuments = (me: Pick<Me, "permissions">) =>
  hasAny(me, "document:read");
export const canReadKnowledge = (me: Pick<Me, "permissions">) =>
  hasAny(me, "knowledge:read");
export const canManageKnowledge = (me: Pick<Me, "permissions">) =>
  hasAny(me, "knowledge:manage");
export const canWriteDocuments = (me: Pick<Me, "permissions">) =>
  hasAny(me, "document:write");
export const canDeleteDocuments = (me: Pick<Me, "permissions">) =>
  hasAny(me, "document:delete");
export const canReadQuotes = (me: Pick<Me, "permissions">) =>
  hasAny(me, "quote:read:all", "quote:read:own");
export const canWriteQuotes = (me: Pick<Me, "permissions">) =>
  hasAny(me, "quote:write:all", "quote:write:own");
export const canApproveQuotes = (me: Pick<Me, "permissions">) =>
  hasAny(me, "quote:approve");
export const canReadContracts = (me: Pick<Me, "permissions">) =>
  hasAny(me, "contract:read:all", "contract:read:own");
export const canWriteContracts = (me: Pick<Me, "permissions">) =>
  hasAny(me, "contract:write:all", "contract:write:own");
/** Activate, terminate and renew (managers and administrators). */
export const canManageContracts = (me: Pick<Me, "permissions">) =>
  hasAny(me, "contract:manage");
export const canManageQuoteSettings = (me: Pick<Me, "permissions">) =>
  hasAny(me, "quote:settings:manage");

export const canReadActivities = (me: Pick<Me, "permissions">) =>
  hasAny(me, "activity:read:all", "activity:read:own");
export const canWriteActivities = (me: Pick<Me, "permissions">) =>
  hasAny(me, "activity:write:all", "activity:write:own");
export const canAssignActivities = (me: Pick<Me, "permissions">) =>
  hasAny(me, "activity:assign");

export const canReadTickets = (me: Pick<Me, "permissions">) =>
  hasAny(me, "ticket:read:all", "ticket:read:own_accounts");
export const canManageTickets = (me: Pick<Me, "permissions">) =>
  hasAny(me, "ticket:manage");

export const canReadOrders = (me: Pick<Me, "permissions">) =>
  hasAny(me, "order:read:all", "order:read:own_accounts");
export const canWriteOrders = (me: Pick<Me, "permissions">) =>
  hasAny(me, "order:write:all", "order:write:own_accounts");

export const canReadInvoices = (me: Pick<Me, "permissions">) =>
  hasAny(me, "invoice:read:all", "invoice:read:own_accounts");
export const canManageInvoices = (me: Pick<Me, "permissions">) =>
  hasAny(me, "invoice:manage");
export const canRecordPayments = (me: Pick<Me, "permissions">) =>
  hasAny(me, "payment:record");

export const canReadUsers = (me: Pick<Me, "permissions">) =>
  hasAny(me, "tenant:user:read");
export const canManageUsers = (me: Pick<Me, "permissions">) =>
  hasAny(me, "tenant:user:manage");
export const canInvitePortalUsers = (me: Pick<Me, "permissions">) =>
  hasAny(me, "portal:user:invite");

export type NavItem = {
  href: string;
  label: string;
  icon:
    | "home"
    | "leads"
    | "accounts"
    | "contacts"
    | "pipeline"
    | "quotes"
    | "contracts"
    | "products"
    | "tasks"
    | "orders"
    | "invoices"
    | "support"
    | "users"
    | "automation"
    | "reports"
    | "knowledge"
    | "assistant"
    | "organisations";
};

/** Sidebar entries for this user. Screens of later workflows are added here as they're built. */
export function navigationFor(
  me: Pick<Me, "permissions" | "user_type">,
): NavItem[] {
  if (me.user_type === "platform")
    return [
      { href: "/", label: "Dashboard", icon: "home" },
      { href: "/platform", label: "Organisations", icon: "organisations" },
    ];
  if (me.user_type !== "staff") return [];
  const items: NavItem[] = [{ href: "/", label: "Dashboard", icon: "home" }];
  if (canReadLeads(me))
    items.push({ href: "/leads", label: "Leads", icon: "leads" });
  if (canReadAccounts(me))
    items.push({ href: "/accounts", label: "Accounts", icon: "accounts" });
  if (canReadContacts(me))
    items.push({ href: "/contacts", label: "Contacts", icon: "contacts" });
  if (canReadOpportunities(me))
    items.push({ href: "/opportunities", label: "Pipeline", icon: "pipeline" });
  if (canReadQuotes(me))
    items.push({ href: "/quotes", label: "Quotes", icon: "quotes" });
  if (canReadContracts(me))
    items.push({ href: "/contracts", label: "Contracts", icon: "contracts" });
  if (canReadActivities(me))
    items.push({ href: "/tasks", label: "Tasks", icon: "tasks" });
  if (canReadOrders(me))
    items.push({ href: "/orders", label: "Orders", icon: "orders" });
  if (canReadInvoices(me))
    items.push({ href: "/invoices", label: "Invoices", icon: "invoices" });
  if (canReadTickets(me))
    items.push({ href: "/tickets", label: "Support", icon: "support" });
  if (canReadCatalog(me))
    items.push({ href: "/products", label: "Products", icon: "products" });
  if (canReadKnowledge(me))
    items.push({ href: "/knowledge", label: "Knowledge", icon: "knowledge" });
  if (canReadTickets(me))
    items.push({ href: "/assistant", label: "AI Assistant", icon: "assistant" });
  if (me.permissions.length > 0 && canUseReports(me))
    items.push({ href: "/reports", label: "Reports", icon: "reports" });
  if (canReadUsers(me))
    items.push({ href: "/users", label: "Users", icon: "users" });
  if (canManageWorkflows(me))
    items.push({
      href: "/automation",
      label: "Automation",
      icon: "automation",
    });
  return items;
}

export const ROLE_LABELS: Record<string, string> = {
  super_admin: "Super Admin",
  tenant_admin: "Tenant Admin",
  sales_manager: "Sales Manager",
  sales_agent: "Sales Agent",
  support_agent: "Support Agent",
  customer: "Customer",
};

/** Plain-language meaning of each permission, for the profile page. */
export const PERMISSION_LABELS: Record<string, string> = {
  "platform:tenant:read": "View organisations on the platform",
  "platform:tenant:manage": "Manage organisations on the platform",
  "tenant:user:read": "View your organisation's users",
  "tenant:user:manage": "Manage your organisation's users",
  "account:read:all": "View all customer accounts",
  "account:read:own": "View your own customer accounts",
  "account:write:all": "Change all customer accounts",
  "account:write:own": "Change your own customer accounts",
  "contact:read:all": "View all contacts",
  "contact:read:own": "View your own contacts",
  "contact:write:all": "Change all contacts",
  "contact:write:own": "Change your own contacts",
  "lead:read:all": "View all leads",
  "lead:read:own": "View your own leads",
  "lead:write:all": "Change all leads",
  "lead:write:own": "Change your own leads",
  "lead:assign": "Assign leads to colleagues",
  "lead:convert": "Convert qualified leads",
  "portal:account:read": "View your company's accounts in the customer portal",
  "ticket:read:all": "View all support tickets",
  "ticket:read:own_accounts": "View support tickets of your own customers",
  "ticket:manage": "Handle support tickets (reply, assign, resolve)",
  "portal:ticket:read": "View your company's support tickets",
  "portal:ticket:write": "Open support tickets and reply",
  "order:read:all": "View all orders",
  "order:read:own_accounts": "View orders of your own customers",
  "order:write:all": "Create, edit and confirm orders for all customers",
  "order:write:own_accounts":
    "Create, edit and confirm orders for your own customers",
  "order:fulfil": "Move orders through fulfilment, shipping and delivery",
  "portal:order:read": "View your company's orders and their status",
  "invoice:read:all": "View all invoices",
  "invoice:read:own_accounts": "View invoices of your own customers",
  "invoice:manage": "Create and issue invoices, issue credit notes",
  "payment:record": "Record received payments and reverse mistaken ones",
  "portal:invoice:read": "View your company's invoices and what is still owed",
  "portal:user:invite": "Invite customer contacts to the portal",
  "opportunity:read:all": "View all opportunities",
  "opportunity:read:own": "View your own opportunities",
  "opportunity:write:all":
    "Manage all opportunities (incl. reopening closed deals)",
  "opportunity:write:own": "Manage your own opportunities",
  "activity:read:all": "View everyone's tasks and activities",
  "activity:read:own": "View your tasks and the activities on your records",
  "activity:write:all": "Change everyone's tasks and activities",
  "activity:write:own": "Create and change your own tasks and activities",
  "activity:assign": "Give tasks to colleagues",
  "catalog:read": "View products and price books",
  "catalog:manage": "Maintain products and prices",
  "quote:read:all": "View all quotes",
  "quote:read:own": "View your own quotes",
  "quote:write:all": "Create and change all quotes",
  "quote:write:own": "Create and change your own quotes",
  "quote:approve": "Approve quotes with large discounts",
  "quote:settings:manage": "Set the discount that needs approval",
  "contract:read:all": "View all contracts",
  "contract:read:own": "View your own contracts",
  "contract:write:all": "Create and change all contracts",
  "contract:write:own": "Create and change your own contracts",
  "contract:manage": "Activate, terminate and renew contracts",
  "document:read": "View documents of customers and deals you can see",
  "document:write": "Upload documents",
  "document:delete": "Delete documents",
  "portal:document:read": "See documents shared with your company",
  "notification:read": "Receive notifications",
  "workflow:manage": "Create automation rules",
  "portal:quote:read": "View your company's quotes in the portal",
  "portal:quote:respond": "Accept or decline quotes in the portal",
  "dashboard:executive": "See the executive dashboard",
  "dashboard:sales:all": "See the sales dashboard of the whole team",
  "dashboard:sales:own": "See your own sales dashboard",
};
