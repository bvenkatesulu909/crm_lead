/**
 * Types of the FastAPI responses this app uses. They mirror docs/api/openapi.json
 * (the backend's committed contract); keep them in sync when the contract changes.
 */

export type UserType = "platform" | "staff" | "customer";

export type Me = {
  user_id: string | null;
  display_name: string | null;
  email: string | null;
  tenant_id: string | null;
  tenant_name: string | null;
  user_type: UserType;
  roles: string[];
  permissions: string[];
};

export const LEAD_STATUSES = [
  "new",
  "contacted",
  "qualified",
  "unqualified",
  "converted",
] as const;
export type LeadStatus = (typeof LEAD_STATUSES)[number];

export const LEAD_SOURCES = [
  "web",
  "referral",
  "event",
  "cold_call",
  "partner",
  "advertisement",
  "other",
] as const;
export type LeadSource = (typeof LEAD_SOURCES)[number];

export const LEAD_SORTS = {
  "-created_at": "Newest first",
  created_at: "Oldest first",
  "-updated_at": "Recently updated",
  last_name: "Last name A–Z",
  "-last_name": "Last name Z–A",
  company_name: "Company A–Z",
  "-score": "Highest score first",
} as const;
export type LeadSort = keyof typeof LEAD_SORTS;

export type Lead = {
  id: string;
  first_name: string | null;
  last_name: string;
  company_name: string | null;
  email: string | null;
  phone: string | null;
  job_title: string | null;
  status: LeadStatus;
  source: LeadSource | null;
  owner_id: string | null;
  converted_at: string | null;
  converted_account_id: string | null;
  converted_contact_id: string | null;
  converted_opportunity_id: string | null;
  created_at: string;
  updated_at: string;
  version: number;
  /** Lead score 0-100 and its band (filled by the API for leads you may see). */
  score?: number | null;
  priority?: "hot" | "warm" | "cold" | null;
};

export type LeadPage = {
  items: Lead[];
  total: number;
  limit: number;
  offset: number;
};

/** Every backend error body (RFC 9457 Problem Details). */
export type ProblemDetails = {
  title: string;
  status: number;
  detail: string;
  code?: string | null;
  request_id?: string | null;
  errors?:
    { location: (string | number)[]; message: string; type: string }[] | null;
};

export type Activity = {
  id: string;
  lead_id: string;
  kind:
    | "note"
    | "call"
    | "email"
    | "meeting"
    | "created"
    | "status_changed"
    | "assigned"
    | "converted";
  subject: string;
  body: string | null;
  occurred_at: string;
  actor_user_id: string | null;
};

export type Assignment = {
  id: string;
  lead_id: string;
  from_user_id: string | null;
  to_user_id: string;
  assigned_by_user_id: string | null;
  reason: string | null;
  assigned_at: string;
};

export type DirectoryUser = {
  id: string;
  display_name: string;
  assignable: boolean;
  support: boolean;
};

export type ConversionResult = {
  lead_id: string;
  account_id: string;
  contact_id: string;
  opportunity_id: string | null;
  converted_at: string;
  already_converted: boolean;
};

export type Account = {
  id: string;
  name: string;
  account_number: string | null;
  website: string | null;
  industry: string | null;
  phone: string | null;
  status: "active" | "inactive";
  segment: Segment | null;
  preferred_channel: Channel | null;
  country: string | null;
  region: string | null;
  city: string | null;
  lifecycle_stage: Lifecycle | null;
  account_type: AccountType;
  preferred_language: string | null;
  owner_id: string | null;
  parent_account_id: string | null;
  created_at: string;
  updated_at: string;
  /** Set when the account is archived (only managers see archived accounts). */
  deleted_at: string | null;
  version: number;
};

export const SEGMENTS = [
  "enterprise",
  "mid_market",
  "small_business",
  "public_sector",
  "non_profit",
] as const;
export type Segment = (typeof SEGMENTS)[number];

export const LIFECYCLE_STAGES = [
  "prospect",
  "onboarding",
  "active_customer",
  "at_risk",
  "churned",
] as const;
export type Lifecycle = (typeof LIFECYCLE_STAGES)[number];
export const ACCOUNT_TYPES = [
  "company",
  "headquarters",
  "subsidiary",
  "branch",
] as const;
export type AccountType = (typeof ACCOUNT_TYPES)[number];

/** Possible matches before creating; matches the user may not see are only counted. */
export type DuplicateCheck = {
  candidates: {
    id: string;
    name: string;
    city?: string | null;
    country?: string | null;
    email?: string | null;
    reasons: string[];
  }[];
  hidden_matches: number;
};

export type CustomerHealth = {
  account_id: string;
  score: number;
  label: "healthy" | "watch" | "at_risk";
  last_interaction_at: string | null;
  days_inactive: number | null;
  inactive: boolean;
  factors: { label: string; impact: number }[];
  lifetime_value: Money[];
};

export type HealthOverview = {
  assessed: number;
  at_risk: number;
  watch: number;
  healthy: number;
  inactive: number;
  items: {
    account_id: string;
    name: string;
    owner_id: string | null;
    lifecycle_stage: Lifecycle | null;
    score: number;
    label: "healthy" | "watch" | "at_risk";
    days_inactive: number | null;
    inactive: boolean;
    top_factor: string | null;
  }[];
};

export type TransferResult = {
  account_id: string;
  previous_owner_id: string | null;
  new_owner_id: string;
  version: number;
  contacts_moved: number;
  opportunities_moved: number;
  tasks_moved: number;
};

export const CHANNELS = ["email", "phone", "mobile", "post", "none"] as const;
export type Channel = (typeof CHANNELS)[number];

export const EMAIL_CONSENTS = ["unknown", "granted", "withdrawn"] as const;
export type EmailConsent = (typeof EMAIL_CONSENTS)[number];

/** One change in an account's or contact's history (from the audit log). */
export type TimelineEntry = {
  at: string;
  action: string;
  title: string;
  changes: Record<string, unknown>;
  actor_name: string | null;
};

export type Contact = {
  id: string;
  first_name: string | null;
  last_name: string;
  email: string | null;
  phone: string | null;
  mobile: string | null;
  job_title: string | null;
  department: string | null;
  account_id: string | null;
  owner_id: string | null;
  is_primary: boolean;
  preferred_channel: Channel | null;
  email_consent: EmailConsent;
  email_consent_at: string | null;
  do_not_call: boolean;
  preferred_language: string | null;
  created_at: string;
  updated_at: string;
  version: number;
};

export type ContactPage = {
  items: Contact[];
  total: number;
  limit: number;
  offset: number;
};

export const OPEN_STAGES = [
  "prospecting",
  "qualification",
  "proposal",
  "negotiation",
] as const;
export type OpenStage = (typeof OPEN_STAGES)[number];
export type Stage = OpenStage | "closed_won" | "closed_lost";

export type Opportunity = {
  id: string;
  name: string;
  account_id: string;
  primary_contact_id: string | null;
  owner_id: string | null;
  stage: Stage;
  /** Chance of winning in %, from the stage. */
  probability: number;
  amount: string | null;
  weighted_amount: string | null;
  currency: string;
  expected_close_date: string | null;
  closed_at: string | null;
  lost_reason: string | null;
  next_step: string | null;
  description: string | null;
  created_at: string;
  updated_at: string;
  version: number;
};

export type BoardColumn = {
  stage: Stage;
  probability: number;
  count: number;
  value: Money[];
  weighted: Money[];
  items: Opportunity[];
};

export type Board = {
  columns: BoardColumn[];
  won: BoardColumn;
  lost: BoardColumn;
};

export type StageChange = {
  from_stage: Stage | null;
  to_stage: Stage;
  note: string | null;
  changed_at: string;
  changed_by_name: string | null;
};

export const ACTIVITY_KINDS = [
  "task",
  "call",
  "meeting",
  "email",
  "note",
] as const;
export type ActivityKind = (typeof ACTIVITY_KINDS)[number];
export const PRIORITIES = ["low", "normal", "high"] as const;
export type Priority = (typeof PRIORITIES)[number];

/** A task, planned follow-up or logged interaction (calls, meetings, e-mails, notes). */
export type CrmActivity = {
  id: string;
  kind: ActivityKind;
  subject: string;
  body: string | null;
  status: "open" | "done" | "cancelled";
  priority: Priority;
  due_at: string | null;
  reminder_at: string | null;
  completed_at: string | null;
  outcome: string | null;
  overdue: boolean;
  assignee_id: string;
  created_by_user_id: string | null;
  related_type: "lead" | "account" | "contact" | "opportunity" | null;
  related_id: string | null;
  created_at: string;
  updated_at: string;
  version: number;
};

export type CrmActivityPage = {
  items: CrmActivity[];
  total: number;
  limit: number;
  offset: number;
};

export type Reminders = {
  overdue: number;
  due_next_24h: number;
  reminders_due: number;
  /** Distinct items needing attention (for the header badge). */
  attention: number;
  items: CrmActivity[];
};

export type OpportunityPage = {
  items: Opportunity[];
  total: number;
  limit: number;
  offset: number;
};

export type AccountPage = {
  items: Account[];
  total: number;
  limit: number;
  offset: number;
};

/** What a customer sees of an account (portal endpoints return no internal fields). */
export type PortalAccount = {
  id: string;
  name: string;
  website: string | null;
  status: "active" | "inactive";
};

export const TICKET_STATUSES = [
  "new",
  "open",
  "pending_customer",
  "resolved",
  "closed",
] as const;
export type TicketStatus = (typeof TICKET_STATUSES)[number];
export const TICKET_PRIORITIES = ["low", "normal", "high", "urgent"] as const;
export type TicketPriority = (typeof TICKET_PRIORITIES)[number];
export const TICKET_CATEGORIES = [
  "question",
  "problem",
  "request",
  "complaint",
  "feedback",
] as const;
export type TicketCategory = (typeof TICKET_CATEGORIES)[number];
export type SlaState = "on_track" | "at_risk" | "breached" | "met";

export type Ticket = {
  id: string;
  number: number;
  account_id: string;
  requester_user_id: string | null;
  subject: string;
  description: string;
  status: TicketStatus;
  priority: TicketPriority;
  channel: "portal" | "staff" | "assistant";
  assignee_user_id: string | null;
  first_response_due_at: string;
  resolution_due_at: string;
  first_responded_at: string | null;
  resolved_at: string | null;
  closed_at: string | null;
  sla_state: SlaState;
  category: TicketCategory;
  satisfaction_rating: number | null;
  satisfaction_comment: string | null;
  rated_at: string | null;
  created_at: string;
  updated_at: string;
  version: number;
};

export type TicketPage = {
  items: Ticket[];
  total: number;
  limit: number;
  offset: number;
};

export type TicketComment = {
  id: string;
  ticket_id: string;
  body: string;
  visibility: "public" | "internal";
  author_user_id: string | null;
  author_name: string;
  author_type: "staff" | "customer" | "system";
  created_at: string;
};

/** Customer view of a ticket: no assignee, SLA or channel. */
export type PortalTicket = {
  id: string;
  number: number;
  account_id: string;
  subject: string;
  description: string;
  status: TicketStatus;
  category: TicketCategory;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
  satisfaction_rating: number | null;
  rated_at: string | null;
};

export type PortalComment = {
  id: string;
  body: string;
  author_name: string;
  author_type: "staff" | "customer" | "system";
  created_at: string;
};

export const ORDER_STATUSES = [
  "draft",
  "confirmed",
  "in_fulfilment",
  "shipped",
  "delivered",
  "cancelled",
] as const;
export type OrderStatus = (typeof ORDER_STATUSES)[number];

/** Money and quantities arrive as decimal STRINGS ("19.99") so no precision is lost. */
export type OrderLine = {
  position: number;
  product_code: string | null;
  description: string;
  quantity: string;
  unit_price: string;
  tax_rate: string;
  line_subtotal: string;
  line_tax: string;
  line_total: string;
};

export type OrderEvent = {
  from_status: OrderStatus | null;
  to_status: OrderStatus;
  actor_name: string;
  note: string | null;
  created_at: string;
};

export type OrderSummary = {
  id: string;
  number: number;
  account_id: string;
  status: OrderStatus;
  currency: string;
  customer_reference: string | null;
  total: string;
  expected_delivery_date: string | null;
  created_at: string;
  updated_at: string;
};

export type OrderPage = {
  items: OrderSummary[];
  total: number;
  limit: number;
  offset: number;
};

/** Staff view of an order. */
export type Order = OrderSummary & {
  created_by_user_id: string | null;
  internal_note: string | null;
  tracking_reference: string | null;
  subtotal: string;
  tax_total: string;
  confirmed_at: string | null;
  shipped_at: string | null;
  delivered_at: string | null;
  cancelled_at: string | null;
  cancellation_reason: string | null;
  version: number;
  lines: OrderLine[];
  events: OrderEvent[];
};

/** Customer view: no internal note, creator, history notes or version. */
export type PortalOrderSummary = {
  id: string;
  number: number;
  account_id: string;
  status: OrderStatus;
  currency: string;
  customer_reference: string | null;
  total: string;
  expected_delivery_date: string | null;
  confirmed_at: string | null;
};

export type PortalOrder = PortalOrderSummary & {
  subtotal: string;
  tax_total: string;
  tracking_reference: string | null;
  shipped_at: string | null;
  delivered_at: string | null;
  cancelled_at: string | null;
  cancellation_reason: string | null;
  lines: OrderLine[];
  timeline: { status: OrderStatus; at: string }[];
};

export type InvoiceStatus = "draft" | "issued" | "discarded";
export const PAYMENT_STATES = [
  "draft",
  "discarded",
  "open",
  "partially_paid",
  "overdue",
  "paid",
  "credited",
] as const;
export type PaymentState = (typeof PAYMENT_STATES)[number];
export const INVOICE_FILTERS = [
  "unpaid",
  "overdue",
  "paid",
  "draft",
  "discarded",
] as const;
export type InvoiceFilter = (typeof INVOICE_FILTERS)[number];
export const PAYMENT_METHODS = [
  "bank_transfer",
  "card",
  "cash",
  "other",
] as const;
export type PaymentMethod = (typeof PAYMENT_METHODS)[number];

/** Lines of invoices and credit notes have the same shape as order lines. */
export type CreditNote = {
  id: string;
  number: number;
  reason: string;
  issue_date: string;
  subtotal: string;
  tax_total: string;
  total: string;
  lines: OrderLine[];
};

export type Payment = {
  id: string;
  amount: string;
  received_on: string;
  method: PaymentMethod;
  reference: string | null;
  recorded_by_name: string;
  reverses_payment_id: string | null;
  reversal_reason: string | null;
  reversed: boolean;
  created_at: string;
};

export type InvoiceSummary = {
  id: string;
  number: number | null;
  order_id: string;
  account_id: string;
  status: InvoiceStatus;
  payment_state: PaymentState;
  currency: string;
  total: string;
  balance_due: string;
  issue_date: string | null;
  due_date: string | null;
  created_at: string;
};

export type InvoicePage = {
  items: InvoiceSummary[];
  total: number;
  limit: number;
  offset: number;
};

/** Staff view of an invoice. */
export type Invoice = InvoiceSummary & {
  customer_reference: string | null;
  created_by_user_id: string | null;
  issued_at: string | null;
  discarded_at: string | null;
  subtotal: string;
  tax_total: string;
  amount_paid: string;
  amount_credited: string;
  version: number;
  lines: OrderLine[];
  credit_notes: CreditNote[];
  payments: Payment[];
};

/** Customer view: issued invoices only, payments that count, no staff details. */
export type PortalInvoiceSummary = {
  id: string;
  number: number;
  order_id: string;
  account_id: string;
  payment_state: PaymentState;
  currency: string;
  total: string;
  balance_due: string;
  issue_date: string;
  due_date: string;
};

export type PortalInvoice = PortalInvoiceSummary & {
  customer_reference: string | null;
  subtotal: string;
  tax_total: string;
  amount_paid: string;
  amount_credited: string;
  lines: OrderLine[];
  credit_notes: CreditNote[];
  payments: {
    amount: string;
    received_on: string;
    method: PaymentMethod;
    reference: string | null;
  }[];
};

export const STAFF_ROLES = [
  "tenant_admin",
  "sales_manager",
  "sales_agent",
  "support_agent",
] as const;
export type StaffRole = (typeof STAFF_ROLES)[number];

/** A person in the organisation, as the Tenant Admin's Users screen sees them. */
export type AdminUser = {
  id: string;
  display_name: string;
  email: string;
  user_type: "staff" | "customer";
  roles: string[];
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
  portal_account_ids: string[];
};

export type AccessRequest = {
  id: string;
  email: string;
  display_name: string;
  status: "pending" | "approved" | "rejected";
  created_at: string;
};

export type PortalUser = {
  id: string;
  display_name: string;
  email: string;
  is_active: boolean;
  last_login_at: string | null;
};

export type OnboardingStatus = {
  state: "member" | "disabled" | "pending" | "rejected" | "none";
  email: string | null;
  email_verified: boolean;
  organisation_name: string | null;
};

export type TenantSummary = {
  id: string;
  slug: string;
  name: string;
  status: string;
};

/** AI assistant (customer portal). */
export type AssistantCitation = {
  document: string;
  heading: string;
  page: number | null;
};

export type AssistantMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  citations: AssistantCitation[];
};

export type AssistantAction = {
  id: string;
  kind: "create_ticket";
  status: "pending" | "confirmed" | "cancelled";
  account_name: string;
  subject: string;
  description: string;
  ticket_number: number | null;
};

export type AssistantConversationSummary = {
  id: string;
  title: string;
  updated_at: string;
};

export type AssistantConversation = AssistantConversationSummary & {
  messages: AssistantMessage[];
  actions: AssistantAction[];
};

// --- Dashboard (GET /dashboard) -------------------------------------------------------------

export const DASHBOARD_VIEWS = [
  "executive",
  "manager",
  "representative",
] as const;
export type DashboardView = (typeof DASHBOARD_VIEWS)[number];

/** An amount in one currency. Totals are never converted between currencies. */
export type Money = { currency: string; amount: string };

export type DashboardLeads = {
  created: number;
  assigned: number;
  unassigned: number;
  new: number;
  contacted: number;
  qualified: number;
  unqualified: number;
  converted: number;
  converted_in_period: number;
  open_now: number;
  conversion_rate: number | null;
};

export type DashboardFollowUp = {
  lead_id: string;
  name: string;
  company: string | null;
  status: LeadStatus;
  owner_name: string | null;
  last_touch_at: string;
  days_idle: number;
};

export type DashboardActivity = {
  at: string;
  kind: string;
  title: string;
  detail: string | null;
  record_type: "lead" | "ticket" | "order";
  record_id: string;
  actor_name: string | null;
};

export type DashboardRep = {
  user_id: string | null;
  name: string;
  leads_created: number;
  qualified: number;
  converted_in_period: number;
  customers: number;
  open_opportunities: number;
  open_value: Money[];
  follow_ups: number;
};

export type LeadScore = {
  lead_id: string;
  score: number;
  priority: "hot" | "warm" | "cold";
  factors: { label: string; points: number }[];
};

export type Dashboard = {
  view: DashboardView;
  available_views: DashboardView[];
  period: { start: string; end: string };
  owner_id: string | null;
  leads: DashboardLeads;
  customers: { total: number; active: number; new_in_period: number };
  pipeline: {
    open_count: number;
    open_value: Money[];
    by_stage: { stage: string; count: number; value: Money[] }[];
    closing_in_period: number;
    closing_in_period_value: Money[];
    without_amount: number;
  };
  follow_ups: { total: number; rule: string; items: DashboardFollowUp[] };
  recent_activities: DashboardActivity[];
  team: DashboardRep[] | null;
  revenue: {
    issued_count: number;
    issued_value: Money[];
    received: Money[];
    outstanding_count: number;
    outstanding: Money[];
    overdue_count: number;
    overdue: Money[];
  } | null;
  orders: {
    confirmed_in_period: number;
    confirmed_value: Money[];
    in_progress_now: number;
  } | null;
  support: {
    open_now: number;
    sla_overdue_now: number;
    opened_in_period: number;
    complaints_in_period: number;
    ratings_in_period: number;
    average_rating: number | null;
  } | null;
};

// --- Catalogue and quotes (Phase E1) -----------------------------------------------------

export type Product = {
  id: string;
  sku: string;
  name: string;
  description: string | null;
  product_type: "product" | "service" | "subscription";
  unit: string;
  tax_rate: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  version: number;
};

export type ProductPage = {
  items: Product[];
  total: number;
  limit: number;
  offset: number;
};

export type PriceBook = {
  id: string;
  name: string;
  currency: string;
  description: string | null;
  is_default: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  version: number;
};

export type Price = {
  product_id: string;
  sku: string;
  name: string;
  unit: string;
  tax_rate: string;
  product_active: boolean;
  unit_price: string;
  currency: string;
  updated_at: string;
};

export const QUOTE_STATUSES = [
  "draft",
  "pending_approval",
  "approved",
  "sent",
  "accepted",
  "declined",
  "superseded",
] as const;
export type QuoteStatus = (typeof QUOTE_STATUSES)[number];

export type QuoteLine = {
  position: number;
  product_id: string;
  sku: string;
  description: string;
  unit: string;
  quantity: string;
  list_price: string;
  discount_percent: string;
  net_unit_price: string;
  tax_rate: string;
  line_gross: string;
  line_discount: string;
  line_subtotal: string;
  line_tax: string;
  line_total: string;
};

type QuoteCore = {
  id: string;
  number: number;
  revision: number;
  title: string;
  account_id: string;
  currency: string;
  status: QuoteStatus;
  valid_until: string;
  expired: boolean;
  customer_note: string | null;
  gross_total: string;
  discount_total: string;
  subtotal: string;
  tax_total: string;
  total: string;
  sent_at: string | null;
  decided_at: string | null;
  created_at: string;
  version: number;
};

export type QuoteSummary = QuoteCore & {
  opportunity_id: string | null;
  owner_id: string | null;
  needs_approval: boolean;
  max_discount_percent: string;
  order_id: string | null;
  updated_at: string;
};

export type Quote = QuoteSummary & {
  revision_of_id: string | null;
  contact_id: string | null;
  created_by_user_id: string | null;
  price_book_id: string;
  internal_note: string | null;
  submitted_at: string | null;
  approved_at: string | null;
  approved_by_user_id: string | null;
  decision_note: string | null;
  lines: QuoteLine[];
  /** Newest e-mail of this quote; null if it was never e-mailed. */
  email_status: "sending" | "sent" | "failed" | null;
};

export type QuotePage = {
  items: QuoteSummary[];
  total: number;
  limit: number;
  offset: number;
};

export type QuoteEvent = {
  from_status: QuoteStatus | null;
  to_status: QuoteStatus;
  note: string | null;
  created_at: string;
  actor_name: string | null;
};

/** What the customer sees: no owner, approval details or internal notes. */
export type PortalQuote = QuoteCore & {
  decision_note: string | null;
  lines: QuoteLine[];
};
export type PortalQuotePage = { items: QuoteCore[]; total: number };

/** Organisation-wide quote settings (GET/PUT /quotes/settings). */
export type QuoteSettings = {
  /** Line discounts ABOVE this percentage need a manager's approval. */
  approval_limit_percent: string;
  /** 0 while the organisation still uses the defaults. */
  version: number;
  updated_at: string | null;
};

/** A document on an account or deal (newest version of its group in lists). */
export type DocumentItem = {
  id: string;
  group_id: string;
  version_no: number;
  record_type: "account" | "opportunity";
  record_id: string;
  file_name: string;
  content_type: string;
  size_bytes: number;
  description: string | null;
  customer_visible: boolean;
  created_at: string;
  created_by_name: string | null;
  versions: number;
};

export type DocumentList = { items: DocumentItem[] };

export type PortalDocument = {
  id: string;
  file_name: string;
  content_type: string;
  size_bytes: number;
  version_no: number;
  created_at: string;
};

/** One message for the signed-in person (ADR 0006). */
export type NotificationItem = {
  id: string;
  type: string;
  title: string;
  /** A page inside the CRM, e.g. /leads/<id>. */
  link: string;
  created_at: string;
  read_at: string | null;
};

export type NotificationPage = { items: NotificationItem[]; unread: number };

export type NotificationPreference = {
  type: string;
  label: string;
  email: boolean;
};

/** Workflow rules (ADR 0006, step 17b). Conditions and actions follow /workflows/catalogue. */
export type RuleCondition = {
  field: string;
  op: string;
  value: string | string[];
};
export type RuleAction =
  | {
      type: "create_task";
      subject: string;
      due_in_days: number;
      assignee: string;
    }
  | { type: "notify"; message: string; to: string }
  | { type: "update_field"; field: string; value: string };

export type WorkflowRule = {
  id: string;
  name: string;
  is_active: boolean;
  trigger: string;
  days: number | null;
  conditions: RuleCondition[];
  actions: RuleAction[];
  created_at: string;
  updated_at: string;
  version: number;
};

export type WorkflowRun = {
  id: string;
  rule_id: string;
  rule_name: string;
  record_type: string;
  record_id: string;
  record_label: string;
  status: "done" | "failed" | "limited";
  message: string | null;
  created_at: string;
};

export type CatalogueField = {
  key: string;
  label: string;
  type: string;
  options: string[];
};
export type CatalogueTrigger = {
  key: string;
  label: string;
  kind: "event" | "schedule";
  record_type: string;
  days_label: string | null;
  fields: CatalogueField[];
  field_updates: CatalogueField[];
};
export type WorkflowCatalogue = {
  triggers: CatalogueTrigger[];
  operators: Record<string, string[]>;
  roles: string[];
  max_conditions: number;
  max_actions: number;
};

/** Reports and the report builder (Phase 18). Values arrive ready to show. */
export type ReportColumn = { key: string; label: string; kind: string };
export type ReportTable = {
  title: string;
  columns: ReportColumn[];
  rows: Record<string, string | number | null>[];
};
export type Report = {
  key: string;
  title: string;
  start: string;
  end: string;
  sections: ReportTable[];
};
export type ReportCatalogue = {
  reports: { key: string; title: string; description: string }[];
  record_types: {
    key: string;
    label: string;
    columns: ReportColumn[];
    statuses: string[];
  }[];
  can_filter_by_rep: boolean;
};
export const KNOWLEDGE_DOCUMENT_STATUSES = [
  "processing",
  "indexed",
  "needs_review",
  "failed",
  "no_text",
] as const;
export type KnowledgeDocumentStatus =
  (typeof KNOWLEDGE_DOCUMENT_STATUSES)[number];

export type KnowledgeDocument = {
  id: string;
  title: string;
  file_name: string;
  content_type: string;
  size_bytes: number;
  status: KnowledgeDocumentStatus;
  visibility: "internal" | "customer_visible";
  page_count: number;
  chunk_count: number;
  error: string | null;
  created_at: string;
};

export type KnowledgeDocumentPage = {
  items: KnowledgeDocument[];
  total: number;
};

export type KnowledgeSearchHit = {
  chunk_id: string;
  document_id: string;
  document_title: string;
  file_name: string;
  heading_path: string;
  page_from: number | null;
  page_to: number | null;
  text: string;
  blocks: string[];
  visibility: "internal" | "customer_visible";
  similarity: number | null;
  keyword_rank: number | null;
  score: number;
  rerank_score: number | null;
};

export type KnowledgeSearchResponse = {
  query: string;
  results: KnowledgeSearchHit[];
  best_similarity: number | null;
  threshold: number | null;
  enough: boolean;
};

export type KnowledgeAnswerSource = {
  chunk_id: string;
  document_id: string;
  document_title: string;
  heading_path: string;
  page_from: number | null;
  page_to: number | null;
  text: string;
};

export type KnowledgeAnswerResponse = {
  query_id: string | null;
  answer: string;
  sources: KnowledgeAnswerSource[];
  exact_chunk_id: string | null;
  enough: boolean;
  model_used: boolean;
  grounded: boolean;
  citations: number[];
};
