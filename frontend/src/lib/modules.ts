import type { Me } from "@/lib/api-types";
import { hasAny } from "@/lib/permissions";

/**
 * The CRM's modules as shown on the dashboard.
 *
 * `status` is the honest build state - no module shows numbers or screens it doesn't have:
 * - "available":   usable now (has a working screen and API)
 * - "in_progress": part of it exists (e.g. the API) but its screens are still being built
 * - "planned":     not built yet; `phase` refers to implementation-plan.md
 *
 * A module only becomes a link when it is available AND the user's permissions allow it.
 * That is for display only - the API checks permissions again on every request.
 */
export type ModuleStatus = "available" | "in_progress" | "planned";

export type ModuleIcon =
  | "leads"
  | "customers"
  | "contacts"
  | "opportunities"
  | "activities"
  | "catalog"
  | "quotes"
  | "orders"
  | "invoices"
  | "support"
  | "portal"
  | "documents"
  | "communication"
  | "marketing"
  | "workflows"
  | "reports"
  | "integrations"
  | "assistant"
  | "knowledge"
  | "administration";

export type CrmModule = {
  key: ModuleIcon;
  name: string;
  description: string;
  status: ModuleStatus;
  phase: number;
  href?: string;
  /** User needs at least one of these to open the module. */
  permissions?: string[];
};

export const CRM_MODULES: CrmModule[] = [
  {
    key: "leads",
    name: "Lead Management",
    description: "Capture, qualify, assign and convert leads",
    status: "available",
    phase: 7,
    href: "/leads",
    permissions: ["lead:read:all", "lead:read:own"],
  },
  {
    key: "customers",
    name: "Customer Management",
    description: "Accounts, contacts, 360° customer profiles and history",
    status: "available",
    phase: 6,
    href: "/accounts",
    permissions: ["account:read:all", "account:read:own"],
  },
  { key: "contacts", name: "Contacts", description: "People at your customers, consent and contact history", status: "available", phase: 6, href: "/contacts", permissions: ["contact:read:all", "contact:read:own"] },
  { key: "opportunities", name: "Sales Opportunities", description: "Pipeline board, stages, won/lost, weighted value", status: "available", phase: 8, href: "/opportunities", permissions: ["opportunity:read:all", "opportunity:read:own"] },
  { key: "activities", name: "Activities", description: "Tasks, follow-ups, call and meeting logs, calendar, reminders", status: "available", phase: 9, href: "/tasks", permissions: ["activity:read:all", "activity:read:own"] },
  { key: "catalog", name: "Product Catalog", description: "Products, services and price books", status: "available", phase: 11, href: "/products", permissions: ["catalog:read"] },
  { key: "quotes", name: "Quotations", description: "Create quotations, approvals and revisions", status: "available", phase: 11, href: "/quotes", permissions: ["quote:read:all", "quote:read:own"] },
  { key: "orders", name: "Orders", description: "Confirmed orders and status tracking", status: "available", phase: 12, href: "/orders", permissions: ["order:read:all", "order:read:own_accounts"] },
  { key: "invoices", name: "Invoices", description: "Invoice generation and payment tracking", status: "available", phase: 13, href: "/invoices", permissions: ["invoice:read:all", "invoice:read:own_accounts"] },
  { key: "support", name: "Customer Support", description: "Support tickets, assignments and SLA", status: "available", phase: 14, href: "/tickets", permissions: ["ticket:read:all", "ticket:read:own_accounts"] },
  { key: "portal", name: "Customer Portal", description: "Customers see their accounts, quotes, orders, invoices and tickets", status: "available", phase: 15 },
  { key: "documents", name: "Documents", description: "Files on customers and deals, with versions; quote PDFs", status: "available", phase: 10, href: "/documents", permissions: ["document:read"] },
  { key: "communication", name: "Communication Center", description: "E-mail composer, templates and conversation history", status: "planned", phase: 17 },
  { key: "marketing", name: "Marketing", description: "Campaigns, segmentation and lead nurturing", status: "planned", phase: 16 },
  { key: "workflows", name: "Workflow & Notifications", description: "Notifications, e-mail reminders and automation rules", status: "available", phase: 17, href: "/notifications", permissions: ["notification:read"] },
  { key: "reports", name: "Reports", description: "Dashboards, standard reports, report builder and CSV export", status: "available", phase: 18, href: "/reports", permissions: ["dashboard:sales:all", "dashboard:sales:own", "quote:read:all", "quote:read:own", "invoice:read:all", "invoice:read:own_accounts", "order:read:all", "order:read:own_accounts", "ticket:read:all", "ticket:read:own_accounts", "account:read:all", "account:read:own"] },
  { key: "integrations", name: "Integrations", description: "SAP/ERP, email, messaging and payments", status: "planned", phase: 19 },
  {
    key: "assistant",
    name: "AI Assistant",
    description: "Staff AI assistant for customer communications",
    status: "available",
    phase: 20,
    href: "/assistant",
    permissions: ["ticket:read:all", "ticket:read:own_accounts"],
  },
  { key: "knowledge", name: "Knowledge Base", description: "Company policies and manuals, indexed with citations", status: "available", phase: 20, href: "/knowledge", permissions: ["knowledge:read"] },
  { key: "administration", name: "Administration", description: "Users, roles, invitations and sign-up approvals", status: "available", phase: 5, href: "/users", permissions: ["tenant:user:read"] },
]; // prettier-ignore

export type ModuleView = CrmModule & {
  /** Link target if this user can open it right now, otherwise undefined. */
  link?: string;
  /** Why it can't be opened (shown to the user). */
  note: string;
};

export function modulesFor(me: Pick<Me, "permissions">): ModuleView[] {
  return CRM_MODULES.map((module) => {
    const allowed = !module.permissions || hasAny(me, ...module.permissions);
    if (module.status === "available" && module.href && allowed) {
      return { ...module, link: module.href, note: "Open" };
    }
    if (module.key === "portal")
      return { ...module, note: "Used by your customers" };
    if (module.status === "available")
      return { ...module, note: "Not included in your role" };
    if (module.status === "in_progress")
      return { ...module, note: "Screens coming soon" };
    return { ...module, note: `Planned · phase ${module.phase}` };
  });
}

/**
 * Modules for the sidebar's "All CRM modules" section: every module except those already in
 * the main menu (same address). Platform operators work outside tenants, so they see none.
 */
export function sidebarModulesFor(
  me: Pick<Me, "permissions" | "user_type">,
  menuHrefs: string[],
): ModuleView[] {
  if (me.user_type !== "staff") return [];
  return modulesFor(me).filter((m) => !(m.link && menuHrefs.includes(m.link)));
}




