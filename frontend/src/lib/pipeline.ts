import type {
  ActivityKind,
  CrmActivity,
  Priority,
  Stage,
} from "@/lib/api-types";

/** Labels and pure helpers for the pipeline and tasks screens (no data access here). */

export const STAGE_LABELS: Record<Stage, string> = {
  prospecting: "Prospecting",
  qualification: "Qualification",
  proposal: "Proposal",
  negotiation: "Negotiation",
  closed_won: "Won",
  closed_lost: "Lost",
};

export const KIND_LABELS: Record<ActivityKind, string> = {
  task: "Task",
  call: "Call",
  meeting: "Meeting",
  email: "E-mail",
  note: "Note",
};

export const PRIORITY_LABELS: Record<Priority, string> = {
  low: "Low",
  normal: "Normal",
  high: "High",
};

const unit = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** "Overdue by 2 days", "Due in 3 hours", "Due in 5 minutes". */
export function dueLabel(dueIso: string, now: Date): string {
  const diff = Date.parse(dueIso) - now.getTime();
  // Decide "overdue" on the exact difference: rounding -30 s gives -0 minutes, not < 0.
  const size = Math.round(Math.abs(diff) / 60_000);
  const span =
    size < 60
      ? unit(Math.max(size, 1), "minute")
      : size < 48 * 60
        ? unit(Math.round(size / 60), "hour")
        : unit(Math.round(size / 1440), "day");
  return diff < 0 ? `Overdue by ${span}` : `Due in ${span}`;
}

export type TaskGroups = {
  overdue: CrmActivity[];
  today: CrmActivity[];
  upcoming: CrmActivity[];
  someday: CrmActivity[];
};

/**
 * Splits OPEN items into overdue / due later today / upcoming / no due date, using the
 * VIEWER'S local day (runs in the browser), so "today" means today where the user is.
 */
export function groupTasks(items: CrmActivity[], now: Date): TaskGroups {
  const endOfToday = new Date(now);
  endOfToday.setHours(24, 0, 0, 0);
  const groups: TaskGroups = {
    overdue: [],
    today: [],
    upcoming: [],
    someday: [],
  };
  for (const item of items) {
    if (item.status !== "open") continue;
    if (item.due_at === null) groups.someday.push(item);
    else if (Date.parse(item.due_at) < now.getTime()) groups.overdue.push(item);
    else if (Date.parse(item.due_at) < endOfToday.getTime())
      groups.today.push(item);
    else groups.upcoming.push(item);
  }
  return groups;
}

/** "2026-10-19T09:30" from a datetime-local input -> exact ISO moment (browser time zone). */
export function localToIso(value: string): string {
  if (!value) return "";
  const moment = new Date(value);
  return Number.isNaN(moment.getTime()) ? "" : moment.toISOString();
}

/** ISO moment -> value for a datetime-local input, in the browser's time zone. */
export function isoToLocal(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Days of a month view (Monday first), with leading/trailing days of nearby months. */
export function monthGrid(year: number, month: number): Date[] {
  const first = new Date(year, month, 1);
  const start = new Date(first);
  start.setDate(1 - ((first.getDay() + 6) % 7));
  const days: Date[] = [];
  for (let i = 0; i < 42; i++) {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    days.push(d);
  }
  // Drop a trailing week that belongs entirely to the next month.
  return days[35].getMonth() !== month ? days.slice(0, 35) : days;
}

export function sameLocalDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

/** "2026-10" -> [2026, 9]; anything invalid -> the given fallback month. */
export function parseMonth(
  value: string | undefined,
  fallback: Date,
): [number, number] {
  const match = /^(\d{4})-(\d{2})$/.exec(value ?? "");
  if (match) {
    const year = Number(match[1]);
    const month = Number(match[2]) - 1;
    if (year >= 2000 && year <= 2100 && month >= 0 && month <= 11)
      return [year, month];
  }
  return [fallback.getFullYear(), fallback.getMonth()];
}

export const monthParam = (year: number, month: number) =>
  `${year}-${String(month + 1).padStart(2, "0")}`;
