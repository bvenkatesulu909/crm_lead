import {
  AGENT_ACTION_STATUSES,
  type AgentAction,
  type AgentActionStatus,
  type Me,
} from "@/lib/api-types";
import { canApproveActions } from "@/lib/permissions";

/**
 * Approval queue helpers (ADR 0014) that need no server: labels, filters and friendlier texts.
 * The API decides everything again - who may decide, whether a proposal is still open.
 */

export const APPROVAL_STATUS_LABELS: Record<AgentActionStatus, string> = {
  pending: "Waiting",
  approved: "Approved",
  rejected: "Rejected",
  expired: "Expired",
  failed: "Could not be carried out",
};

/** Whether to show the decision buttons: an approver, a waiting proposal, someone else's. */
export function canDecideOn(
  me: Pick<Me, "permissions" | "user_id">,
  action: Pick<AgentAction, "status" | "requested_by_user_id">,
): boolean {
  return (
    canApproveActions(me) &&
    action.status === "pending" &&
    action.requested_by_user_id !== me.user_id
  );
}

const NOTE_MAX = 500;

/** The note of a decision: optional when approving, required when rejecting. */
export function checkDecisionNote(
  note: string,
  required: boolean,
): string | null {
  const text = note.trim();
  if (!text)
    return required ? "Say why you reject it, so the colleague knows." : null;
  if (text.length > NOTE_MAX)
    return `Please keep the note under ${NOTE_MAX} characters.`;
  return null;
}

const DECISION_ERRORS: Record<string, string> = {
  agent_action_already_decided:
    "This proposal was already decided by someone else.",
  agent_action_changed:
    "The proposal changed in the meantime. Please reload the page.",
  agent_action_expired:
    "This proposal has expired and can't be approved any more.",
  self_approval_forbidden: "You can't decide on your own proposal.",
  record_not_found:
    "You can't see the record this proposal is about, so you can't decide it.",
  agent_action_not_found: "This proposal doesn't exist any more.",
};

export function decisionErrorText(
  code: string | undefined,
  fallback?: string,
): string {
  return (
    (code && DECISION_ERRORS[code]) ||
    fallback ||
    "The decision could not be saved."
  );
}

// --- the list -------------------------------------------------------------------------------

export type ApprovalTab = "waiting" | "mine" | "all";
export type ApprovalFilters = {
  tab: ApprovalTab;
  status: AgentActionStatus | "";
  page: number;
};

export const APPROVAL_TABS: { key: ApprovalTab; label: string }[] = [
  { key: "waiting", label: "Waiting" },
  { key: "mine", label: "My proposals" },
  { key: "all", label: "History" },
];

type RawParams = Record<string, string | string[] | undefined>;

export function parseApprovalFilters(raw: RawParams): ApprovalFilters {
  const one = (v: string | string[] | undefined) =>
    (Array.isArray(v) ? v[0] : v) ?? "";
  const tab = one(raw.tab);
  const status = one(raw.status);
  return {
    tab: tab === "mine" || tab === "all" ? tab : "waiting",
    status: (AGENT_ACTION_STATUSES as readonly string[]).includes(status)
      ? (status as AgentActionStatus)
      : "",
    page: Math.min(Math.max(Number.parseInt(one(raw.page), 10) || 1, 1), 5000),
  };
}

/** The API query for one page: "waiting" = pending, "mine" = my own, "history" = any status. */
export function approvalQuery(
  filters: ApprovalFilters,
  pageSize: number,
): URLSearchParams {
  const query = new URLSearchParams({
    limit: String(pageSize),
    offset: String((filters.page - 1) * pageSize),
  });
  if (filters.tab === "waiting") query.set("status", "pending");
  else if (filters.tab === "mine") query.set("mine", "true");
  else if (filters.status) query.set("status", filters.status);
  return query;
}

export function approvalPageHref(
  filters: ApprovalFilters,
  page: number,
): string {
  const p = new URLSearchParams();
  if (filters.tab !== "waiting") p.set("tab", filters.tab);
  if (filters.tab === "all" && filters.status) p.set("status", filters.status);
  if (page > 1) p.set("page", String(page));
  return p.toString() ? `/approvals?${p}` : "/approvals";
}

const FIELD_LABELS: Record<string, string> = {
  status: "Status",
  owner_id: "Owner",
  task: "New task",
};
const PERSON_FIELDS = new Set(["owner_id", "assignee_id"]);

export function fieldLabel(field: string): string {
  return FIELD_LABELS[field] ?? field;
}

function plain(value: unknown): string {
  if (value === null || value === undefined) return "nothing";
  return typeof value === "string" ? value : JSON.stringify(value);
}

/**
 * One planned change as a sentence (ADR 0018). The values are ids and codes from the plan the
 * proposal stored; people are shown by name, a missing owner as "nobody". Anything a model
 * wrote (a task subject) stays plain text - React escapes it where it is shown.
 */
export function describeChange(
  change: { field: string; before: unknown; after: unknown },
  nameOf: (id: string | null) => string,
): string {
  const label = fieldLabel(change.field);
  if (
    change.field === "task" &&
    change.after &&
    typeof change.after === "object"
  ) {
    const task = change.after as {
      subject?: unknown;
      due_in_days?: unknown;
      assignee_id?: unknown;
    };
    const days = Number(task.due_in_days);
    const due = Number.isFinite(days)
      ? `, due in ${days} ${days === 1 ? "day" : "days"}`
      : "";
    const who =
      typeof task.assignee_id === "string"
        ? `, for ${nameOf(task.assignee_id)}`
        : "";
    return `${label}: ${plain(task.subject)}${due}${who}`;
  }
  const show = (value: unknown) =>
    PERSON_FIELDS.has(change.field)
      ? value
        ? nameOf(String(value))
        : "nobody"
      : plain(value);
  return `${label}: ${show(change.before)} → ${show(change.after)}`;
}
