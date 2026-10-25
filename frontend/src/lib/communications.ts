import {
  EMAIL_DIRECTIONS,
  EMAIL_STATUSES,
  type EmailDirection,
  type EmailMessage,
  type EmailStatus,
} from "@/lib/api-types";

/**
 * Communication Center helpers (ADR 0012) that need no server: labels, filters and the form
 * checks that mirror the backend's rules. The API checks everything again - these only give
 * quicker, friendlier messages.
 */

export const EMAIL_STATUS_LABELS: Record<EmailStatus, string> = {
  queued: "Sending",
  sent: "Sent",
  failed: "Not delivered",
  logged: "Received",
};

export const EMAIL_DIRECTION_LABELS: Record<EmailDirection, string> = {
  outbound: "Sent by us",
  inbound_logged: "Received (logged)",
};

/** What the sender is told when an e-mail could not be delivered (codes from the API). */
export const EMAIL_FAILURE_LABELS: Record<string, string> = {
  recipient_refused: "The mail server refused the address.",
  mail_server_unavailable: "The mail server could not be reached.",
  consent_withdrawn: "The contact withdrew consent before it was sent.",
  recipient_gone: "The lead or contact no longer exists.",
  send_failed: "It could not be sent.",
};

export function failureText(code: string | null): string {
  return code ? (EMAIL_FAILURE_LABELS[code] ?? EMAIL_FAILURE_LABELS.send_failed) : "";
}

/** The record an e-mail card sits on. */
export type EmailRecord = {
  type: "lead" | "contact" | "account" | "opportunity";
  id: string;
};

const RECORD_PATHS: Record<EmailRecord["type"], string> = {
  lead: "/leads",
  contact: "/contacts",
  account: "/accounts",
  opportunity: "/opportunities",
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export const isUuid = (value: string) => UUID.test(value);

/** The page of the record (also where a form goes back to after saving). */
export function recordPath(record: EmailRecord): string {
  if (!(record.type in RECORD_PATHS) || !isUuid(record.id))
    throw new Error("invalid record");
  return `${RECORD_PATHS[record.type]}/${record.id}`;
}

/** Where an e-mail in the list leads: the lead or contact it was with. */
export function messageRecordHref(m: Pick<EmailMessage, "lead_id" | "contact_id">) {
  if (m.lead_id) return `/leads/${m.lead_id}`;
  if (m.contact_id) return `/contacts/${m.contact_id}`;
  return null;
}

// --- the Communication Center list --------------------------------------------------------

export type EmailFilters = {
  q: string;
  status: EmailStatus | "";
  direction: EmailDirection | "";
  page: number;
};

type RawParams = Record<string, string | string[] | undefined>;

export function parseEmailFilters(raw: RawParams): EmailFilters {
  const one = (v: string | string[] | undefined) =>
    (Array.isArray(v) ? v[0] : v) ?? "";
  const status = one(raw.status);
  const direction = one(raw.direction);
  return {
    q: one(raw.q).trim().slice(0, 100),
    status: (EMAIL_STATUSES as readonly string[]).includes(status)
      ? (status as EmailStatus)
      : "",
    direction: (EMAIL_DIRECTIONS as readonly string[]).includes(direction)
      ? (direction as EmailDirection)
      : "",
    page: Math.min(Math.max(Number.parseInt(one(raw.page), 10) || 1, 1), 5000),
  };
}

/** The API query for one page of the list. */
export function emailQuery(filters: EmailFilters, pageSize: number): URLSearchParams {
  const query = new URLSearchParams({
    limit: String(pageSize),
    offset: String((filters.page - 1) * pageSize),
  });
  if (filters.q) query.set("q", filters.q);
  if (filters.status) query.set("status", filters.status);
  if (filters.direction) query.set("direction", filters.direction);
  return query;
}

/** The address of a page of the list, keeping the filters. */
export function emailPageHref(filters: EmailFilters, page: number): string {
  const p = new URLSearchParams();
  if (filters.q) p.set("q", filters.q);
  if (filters.status) p.set("status", filters.status);
  if (filters.direction) p.set("direction", filters.direction);
  if (page > 1) p.set("page", String(page));
  return p.toString() ? `/communications?${p}` : "/communications";
}

// --- form checks (mirror the backend) -----------------------------------------------------

const SUBJECT_MAX = 200;
const BODY_MAX = 50_000;
const TEMPLATE_BODY_MAX = 20_000;
const TEMPLATE_NAME_MAX = 120;

export type Checked<T> =
  | { ok: true; data: T }
  | { ok: false; fieldErrors: Record<string, string> };

export type MessageFields = { subject: string; body: string };

/** Subject and text of an e-mail to send or to log. */
export function checkMessage(values: Record<string, string>): Checked<MessageFields> {
  const subject = (values.subject ?? "").trim();
  const body = values.body ?? "";
  const fieldErrors: Record<string, string> = {};
  if (!subject) fieldErrors.subject = "Enter a subject.";
  else if (subject.length > SUBJECT_MAX)
    fieldErrors.subject = `At most ${SUBJECT_MAX} characters.`;
  if (!body.trim()) fieldErrors.body = "Write the text of the e-mail.";
  else if (body.length > BODY_MAX) fieldErrors.body = `At most ${BODY_MAX} characters.`;
  return Object.keys(fieldErrors).length
    ? { ok: false, fieldErrors }
    : { ok: true, data: { subject, body } };
}

// The placeholder rules of the backend (communications/rules.py): a fixed list, nothing else.
export const PLACEHOLDER_NAMES = [
  "recipient.first_name",
  "recipient.full_name",
  "recipient.company",
  "sender.name",
  "sender.email",
  "organisation.name",
] as const;
const TOKEN = /\{\{\s*([^{}]*?)\s*\}\}/g;

/** Unknown placeholders (as {{name}}) and unbalanced braces, each once, in order. */
export function placeholderProblems(text: string): string[] {
  const problems: string[] = [];
  for (const match of text.matchAll(TOKEN))
    if (!(PLACEHOLDER_NAMES as readonly string[]).includes(match[1]))
      problems.push(`{{${match[1]}}}`);
  const rest = text.replace(TOKEN, "\u0000");
  if (rest.includes("{{")) problems.push("'{{' without '}}'");
  if (rest.includes("}}")) problems.push("'}}' without '{{'");
  return [...new Set(problems)];
}

export type TemplateFields = { name: string; subject: string; body: string };

export function checkTemplate(values: Record<string, string>): Checked<TemplateFields> {
  const name = (values.name ?? "").trim();
  const subject = (values.subject ?? "").trim();
  const body = values.body ?? "";
  const fieldErrors: Record<string, string> = {};
  if (!name) fieldErrors.name = "Give the template a name.";
  else if (name.length > TEMPLATE_NAME_MAX)
    fieldErrors.name = `At most ${TEMPLATE_NAME_MAX} characters.`;
  if (!subject) fieldErrors.subject = "Enter a subject.";
  else if (subject.length > SUBJECT_MAX)
    fieldErrors.subject = `At most ${SUBJECT_MAX} characters.`;
  if (!body.trim()) fieldErrors.body = "Write the text of the template.";
  else if (body.length > TEMPLATE_BODY_MAX)
    fieldErrors.body = `At most ${TEMPLATE_BODY_MAX} characters.`;
  for (const [field, text] of [
    ["subject", subject],
    ["body", body],
  ] as const) {
    const problems = placeholderProblems(text);
    if (problems.length && !fieldErrors[field])
      fieldErrors[field] = `Unknown or broken placeholders: ${problems.join(", ")}.`;
  }
  return Object.keys(fieldErrors).length
    ? { ok: false, fieldErrors }
    : { ok: true, data: { name, subject, body } };
}

// --- who can be written to (mirrors the API's checks) --------------------------------------

export type EmailMode = "send" | "log";

/** A person on the page: a lead (no consent field) or a contact. */
export type EmailPerson = {
  email: string | null;
  email_consent?: "unknown" | "granted" | "withdrawn";
};

const ADDRESS = /^[^@\s]+@[^@\s]+$/;

/**
 * Why this person can't be chosen, or null. Both sending and logging need an address (it is
 * taken from the record); only sending respects withdrawn consent - receiving is always fine.
 */
export function blockedReason(person: EmailPerson, mode: EmailMode): string | null {
  if (!person.email || !ADDRESS.test(person.email)) return "no e-mail address";
  if (mode === "send" && person.email_consent === "withdrawn")
    return "asked not to receive e-mails";
  return null;
}

/** The contacts of an account or deal, as choices for the "To" / "From" list. */
export function recipientOptions(
  contacts: (EmailPerson & { id: string; first_name: string | null; last_name: string })[],
  mode: EmailMode,
): { id: string; label: string; blocked?: string }[] {
  return contacts.map((c) => {
    const name = [c.first_name, c.last_name].filter(Boolean).join(" ");
    const blocked = blockedReason(c, mode);
    return blocked
      ? { id: c.id, label: name, blocked }
      : { id: c.id, label: `${name} <${c.email}>` };
  });
}
