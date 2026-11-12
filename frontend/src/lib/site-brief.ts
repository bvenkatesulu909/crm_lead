/** Words for the rep's brief before a site visit (ADR 0029). */
import type { SiteBrief } from "@/lib/api-types";
import { formatDate } from "@/lib/format";

/** "Confirm" (check an assumption) or "Ask" (something we do not know yet). */
export const askBadge = (kind: "confirm" | "gap") =>
  kind === "confirm" ? "Confirm" : "Ask";

const ENTRY_KINDS: Record<string, string> = {
  note: "Note",
  call: "Call",
  email: "E-mail",
  meeting: "Meeting",
};

export const entryKind = (kind: string) => ENTRY_KINDS[kind] ?? "Note";

export const statusText = (status: string) =>
  status ? status.charAt(0).toUpperCase() + status.slice(1) : "";

/** "Overdue since 10 Nov 2026", "Due 14 Nov 2026" or "No due date". */
export function dueText(task: SiteBrief["tasks"][number]): string {
  if (!task.due_at) return "No due date";
  return task.overdue
    ? `Overdue since ${formatDate(task.due_at)}`
    : `Due ${formatDate(task.due_at)}`;
}
