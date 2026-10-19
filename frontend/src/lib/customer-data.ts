import type {
  AccountType,
  Channel,
  Lifecycle,
  EmailConsent,
  Segment,
  TimelineEntry,
} from "@/lib/api-types";

/** Display labels and helpers for accounts and contacts (no data access here). */

export const SEGMENT_LABELS: Record<Segment, string> = {
  enterprise: "Enterprise",
  mid_market: "Mid-market",
  small_business: "Small business",
  public_sector: "Public sector",
  non_profit: "Non-profit",
};

export const CHANNEL_LABELS: Record<Channel, string> = {
  email: "E-mail",
  phone: "Phone",
  mobile: "Mobile",
  post: "Post",
  none: "No contact",
};

export const CONSENT_LABELS: Record<EmailConsent, string> = {
  unknown: "Not asked yet",
  granted: "Agreed to e-mails",
  withdrawn: "Opted out of e-mails",
};

export const LIFECYCLE_LABELS: Record<Lifecycle, string> = {
  prospect: "Prospect",
  onboarding: "Onboarding",
  active_customer: "Active customer",
  at_risk: "At risk",
  churned: "Churned",
};

export const ACCOUNT_TYPE_LABELS: Record<AccountType, string> = {
  company: "Company",
  headquarters: "Headquarters",
  subsidiary: "Subsidiary",
  branch: "Branch",
};

export const HEALTH_LABELS = {
  healthy: "Healthy",
  watch: "Watch",
  at_risk: "At risk",
} as const;

/** A short list for forms; any ISO 639-1 code is accepted by the API. */
export const LANGUAGES: [string, string][] = [
  ["en", "English"], ["hi", "Hindi"], ["te", "Telugu"], ["ta", "Tamil"], ["kn", "Kannada"],
  ["mr", "Marathi"], ["bn", "Bengali"], ["de", "German"], ["fr", "French"], ["es", "Spanish"],
  ["it", "Italian"], ["nl", "Dutch"], ["pt", "Portuguese"], ["ar", "Arabic"], ["zh", "Chinese"],
  ["ja", "Japanese"],
]; // prettier-ignore

/** A short list for forms and filters; any ISO 3166 code is accepted by the API. */
export const COUNTRIES: [string, string][] = [
  ["IN", "India"], ["GB", "United Kingdom"], ["US", "United States"], ["DE", "Germany"],
  ["FR", "France"], ["NL", "Netherlands"], ["ES", "Spain"], ["IT", "Italy"], ["AE", "United Arab Emirates"],
  ["SG", "Singapore"], ["AU", "Australia"], ["CA", "Canada"], ["JP", "Japan"], ["CN", "China"],
]; // prettier-ignore

export const countryName = (code: string | null) =>
  code ? (COUNTRIES.find(([c]) => c === code)?.[1] ?? code) : "—";
export const languageName = (code: string | null) =>
  code ? (LANGUAGES.find(([c]) => c === code)?.[1] ?? code) : "—";

export const STAGE_LABELS: Record<string, string> = {
  prospecting: "Prospecting",
  qualification: "Qualification",
  proposal: "Proposal",
  negotiation: "Negotiation",
  closed_won: "Won",
  closed_lost: "Lost",
};

const FIELD_LABELS: Record<string, string> = {
  name: "Name",
  account_number: "Account number",
  website: "Website",
  industry: "Industry",
  phone: "Phone",
  segment: "Segment",
  preferred_channel: "Preferred channel",
  parent_account_id: "Parent account",
  owner_id: "Owner",
  status: "Status",
  first_name: "First name",
  last_name: "Last name",
  email: "E-mail",
  mobile: "Mobile",
  job_title: "Designation",
  department: "Department",
  account_id: "Account",
  is_primary: "Primary contact",
  email_consent: "E-mail consent",
  do_not_call: "Do not call",
  country: "Country",
  region: "Region",
  city: "City",
  lifecycle_stage: "Lifecycle stage",
  account_type: "Account type",
  preferred_language: "Preferred language",
};

// IDs mean nothing to a reader; these fields show "changed" instead of raw values.
const ID_FIELDS = new Set(["owner_id", "parent_account_id", "account_id"]);

function show(field: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  const text = String(value);
  if (field === "segment") return SEGMENT_LABELS[text as Segment] ?? text;
  if (field === "preferred_channel")
    return CHANNEL_LABELS[text as Channel] ?? text;
  if (field === "email_consent")
    return CONSENT_LABELS[text as EmailConsent] ?? text;
  if (field === "lifecycle_stage")
    return LIFECYCLE_LABELS[text as Lifecycle] ?? text;
  if (field === "account_type")
    return ACCOUNT_TYPE_LABELS[text as AccountType] ?? text;
  if (field === "country") return countryName(text);
  if (field === "preferred_language") return languageName(text);
  return text;
}

const isChange = (v: unknown): v is { old: unknown; new: unknown } =>
  typeof v === "object" && v !== null && "old" in v && "new" in v;

/** "Segment: Enterprise → Mid-market" lines for one history entry. */
export function describeChanges(entry: TimelineEntry): string[] {
  const lines: string[] = [];
  const created = entry.action.endsWith(".created");
  for (const [field, value] of Object.entries(entry.changes)) {
    const label = FIELD_LABELS[field];
    if (isChange(value) && label) {
      if (created && (value.new === null || value.new === false)) continue;
      if (ID_FIELDS.has(field)) {
        lines.push(value.new === null ? `${label} removed` : `${label} set`);
        continue;
      }
      lines.push(
        created
          ? `${label}: ${show(field, value.new)}`
          : `${label}: ${show(field, value.old)} → ${show(field, value.new)}`,
      );
    } else if (field === "reason" && value) {
      lines.push(`Reason: ${String(value)}`);
    } else if (
      (field === "contact_name" || field === "child_name") &&
      typeof value === "string"
    ) {
      lines.push(value);
    }
  }
  return lines;
}

export function contactName(c: {
  first_name: string | null;
  last_name: string;
}): string {
  return [c.first_name, c.last_name].filter(Boolean).join(" ");
}

export type RelationshipEvent = {
  at: string;
  title: string;
  details: string[];
  href?: string;
  by: string | null;
};

const pad = (n: number) => String(n).padStart(4, "0");

/**
 * One customer relationship timeline, newest first: account and contact changes from the
 * audit log plus orders, invoices, support tickets and converted leads that the user could
 * already see on the page. Nothing is invented: each item is a real record with its own date.
 */
export function relationshipTimeline(
  sources: {
    audit?: TimelineEntry[];
    orders?: { id: string; number: number; created_at: string; total: string; currency: string; status: string }[];
    invoices?: { id: string; number: number | null; issue_date: string | null; total: string; currency: string }[];
    tickets?: { id: string; number: number; created_at: string; subject: string }[];
    leads?: { id: string; first_name: string | null; last_name: string; converted_at: string | null }[];
  },
  limit = 30,
): RelationshipEvent[] {
  const events: RelationshipEvent[] = [];
  for (const entry of sources.audit ?? [])
    events.push({ at: entry.at, title: entry.title, details: describeChanges(entry), by: entry.actor_name });
  for (const o of sources.orders ?? [])
    events.push({ at: o.created_at, title: `Order SO-${pad(o.number)} created`, details: [`${o.total} ${o.currency} · now ${o.status.replace(/_/g, " ")}`], href: `/orders/${o.id}`, by: null });
  for (const i of sources.invoices ?? [])
    if (i.number !== null && i.issue_date)
      events.push({ at: `${i.issue_date}T00:00:00Z`, title: `Invoice INV-${pad(i.number)} issued`, details: [`${i.total} ${i.currency}`], href: `/invoices/${i.id}`, by: null });
  for (const t of sources.tickets ?? [])
    events.push({ at: t.created_at, title: `Support ticket T-${pad(t.number)} opened`, details: [t.subject], href: `/tickets/${t.id}`, by: null });
  for (const l of sources.leads ?? [])
    if (l.converted_at)
      events.push({ at: l.converted_at, title: `Lead converted: ${contactName(l)}`, details: [], href: `/leads/${l.id}`, by: null });
  return events
    .sort((a, b) => Date.parse(b.at) - Date.parse(a.at))
    .slice(0, limit);
} // prettier-ignore
