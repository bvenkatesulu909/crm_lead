import {
  DASHBOARD_VIEWS,
  type DashboardView,
  type Me,
  type Money,
} from "@/lib/api-types";
import { hasAny } from "@/lib/permissions";

/**
 * Dashboard filters live in the URL (?range=30d&view=manager&rep=<id>), so a filtered dashboard
 * can be bookmarked or shared and works without client-side JavaScript. Everything here only
 * shapes the request: the API checks the view, the rep and the dates again.
 */

export const RANGES = [
  { key: "7d", label: "Last 7 days" },
  { key: "30d", label: "Last 30 days" },
  { key: "90d", label: "Last 90 days" },
  { key: "month", label: "This month" },
  { key: "year", label: "This year" },
] as const;
export type RangeKey = (typeof RANGES)[number]["key"] | "custom";

export const VIEW_LABELS: Record<DashboardView, string> = {
  executive: "Executive",
  manager: "Sales manager",
  representative: "My sales",
};

export const STAGE_LABELS: Record<string, string> = {
  prospecting: "Prospecting",
  qualification: "Qualification",
  proposal: "Proposal",
  negotiation: "Negotiation",
};

export type DashboardFilters = {
  range: RangeKey;
  start: string; // YYYY-MM-DD
  end: string;
  view: DashboardView | "";
  rep: string;
};

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type Raw = Record<string, string | string[] | undefined>;
const one = (v: string | string[] | undefined) =>
  (Array.isArray(v) ? v[0] : v) ?? "";

/** YYYY-MM-DD of a date in UTC (the API counts days in UTC). */
export function isoDay(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function validDay(value: string): boolean {
  return (
    ISO_DATE.test(value) && !Number.isNaN(Date.parse(`${value}T00:00:00Z`))
  );
}

/** First and last day of a preset, ending today. */
export function rangeDates(range: RangeKey, today: Date): [string, string] {
  const end = isoDay(today);
  const d = new Date(
    Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()),
  );
  switch (range) {
    case "7d":
      d.setUTCDate(d.getUTCDate() - 6);
      break;
    case "90d":
      d.setUTCDate(d.getUTCDate() - 89);
      break;
    case "month":
      d.setUTCDate(1);
      break;
    case "year":
      d.setUTCMonth(0, 1);
      break;
    default: // 30d (and the fallback for anything unknown)
      d.setUTCDate(d.getUTCDate() - 29);
  }
  return [isoDay(d), end];
}

export function parseDashboardFilters(raw: Raw, today: Date): DashboardFilters {
  const view = one(raw.view);
  const rep = one(raw.rep);
  const range = one(raw.range);
  const from = one(raw.from);
  const to = one(raw.to);
  const filters = {
    view: (DASHBOARD_VIEWS as readonly string[]).includes(view)
      ? (view as DashboardView)
      : "",
    rep: UUID.test(rep) ? rep.toLowerCase() : "",
  } as const;
  // Custom dates win when both are valid; otherwise fall back to a preset.
  if ((range === "custom" || !range) && validDay(from) && validDay(to)) {
    return { ...filters, range: "custom", start: from, end: to };
  }
  const preset = RANGES.some((r) => r.key === range)
    ? (range as RangeKey)
    : "30d";
  const [start, end] = rangeDates(preset, today);
  return { ...filters, range: preset, start, end };
}

/** Query string for GET /dashboard. */
export function dashboardQuery(f: DashboardFilters): string {
  const q = new URLSearchParams({ start: f.start, end: f.end });
  if (f.view) q.set("view", f.view);
  // Only managers' views accept a rep filter; the API refuses it for the own-sales view.
  if (f.rep && f.view !== "representative") q.set("owner_id", f.rep);
  return q.toString();
}

/** Link to the dashboard with some filters changed (keeps the others). */
export function dashboardHref(
  f: DashboardFilters,
  change: Partial<DashboardFilters>,
): string {
  const next = { ...f, ...change };
  const q = new URLSearchParams();
  if (next.range === "custom") {
    q.set("range", "custom");
    q.set("from", next.start);
    q.set("to", next.end);
  } else if (next.range !== "30d") {
    q.set("range", next.range);
  }
  if (next.view) q.set("view", next.view);
  if (next.rep && next.view !== "representative") q.set("rep", next.rep);
  const s = q.toString();
  return s ? `/?${s}` : "/";
}

export const hasDashboard = (me: Pick<Me, "permissions">) =>
  hasAny(
    me,
    "dashboard:executive",
    "dashboard:sales:all",
    "dashboard:sales:own",
  );

/** "EUR 1,500.50 · USD 20.00"; "—" when there is nothing. Currencies are never added up. */
export function formatAmounts(values: Money[]): string {
  if (values.length === 0) return "—";
  return values
    .map(({ amount, currency }) =>
      // Intl accepts decimal strings exactly (ES2023); the TS types still say number.
      new Intl.NumberFormat("en-GB", { style: "currency", currency }).format(
        amount as unknown as number,
      ),
    )
    .join(" · ");
}

export function formatRate(rate: number | null): string {
  return rate === null ? "—" : `${Math.round(rate * 1000) / 10}%`;
}

const dayFormat = new Intl.DateTimeFormat("en-GB", {
  dateStyle: "medium",
  timeZone: "UTC",
});

export function formatPeriod(start: string, end: string): string {
  const s = dayFormat.format(new Date(`${start}T00:00:00Z`));
  const e = dayFormat.format(new Date(`${end}T00:00:00Z`));
  return s === e ? s : `${s} – ${e}`;
}

export function recordHref(type: "lead" | "ticket" | "order", id: string) {
  return {
    lead: `/leads/${id}`,
    ticket: `/tickets/${id}`,
    order: `/orders/${id}`,
  }[type];
}
