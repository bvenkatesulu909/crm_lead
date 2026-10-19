import Link from "next/link";
import type { ReactNode } from "react";

import {
  Card,
  EmptyState,
  StatusBadge,
  buttonClass,
  cx,
} from "@/components/ui";
import type { Dashboard, DashboardView, DirectoryUser } from "@/lib/api-types";
import {
  RANGES,
  STAGE_LABELS,
  VIEW_LABELS,
  dashboardHref,
  formatAmounts,
  formatPeriod,
  formatRate,
  recordHref,
  type DashboardFilters,
} from "@/lib/dashboard";
import { formatDateTime } from "@/lib/format";

const field =
  "mt-1 block w-full rounded-md border-0 bg-white px-3 py-2 text-sm text-slate-900 ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-brand-600";

// --- Filters -------------------------------------------------------------------------------------

/** View tabs (only when the role has more than one dashboard). */
export function ViewTabs({
  views,
  current,
  filters,
}: {
  views: DashboardView[];
  current: DashboardView;
  filters: DashboardFilters;
}) {
  if (views.length < 2) return null;
  return (
    <nav aria-label="Dashboard view" className="mb-4 flex flex-wrap gap-2">
      {views.map((view) => (
        <Link
          key={view}
          href={dashboardHref(filters, {
            view,
            rep: view === "representative" ? "" : filters.rep,
          })}
          aria-current={view === current ? "page" : undefined}
          className={cx(
            "rounded-full px-4 py-1.5 text-sm font-medium ring-1 ring-inset",
            view === current
              ? "bg-brand-600 text-white ring-brand-600"
              : "bg-white text-slate-700 ring-slate-300 hover:bg-slate-50",
          )}
        >
          {VIEW_LABELS[view]}
        </Link>
      ))}
    </nav>
  );
}

/** A plain GET form: works without JavaScript and keeps the filters in the URL. */
export function FilterBar({
  filters,
  view,
  reps,
}: {
  filters: DashboardFilters;
  view: DashboardView;
  reps: DirectoryUser[] | null;
}) {
  return (
    <Card className="mb-6 p-4">
      <form
        method="get"
        action="/"
        aria-label="Dashboard filters"
        className="grid grid-cols-2 items-end gap-3 md:grid-cols-[repeat(4,minmax(0,1fr))_auto]"
      >
        {filters.view && (
          <input type="hidden" name="view" value={filters.view} />
        )}
        <label className="col-span-2 block text-sm font-medium text-slate-700 md:col-span-1">
          Period
          <select name="range" defaultValue={filters.range} className={field}>
            {RANGES.map((r) => (
              <option key={r.key} value={r.key}>
                {r.label}
              </option>
            ))}
            <option value="custom">Custom dates</option>
          </select>
        </label>
        <label className="block text-sm font-medium text-slate-700">
          From
          <input
            type="date"
            name="from"
            defaultValue={filters.start}
            className={field}
          />
        </label>
        <label className="block text-sm font-medium text-slate-700">
          To
          <input
            type="date"
            name="to"
            defaultValue={filters.end}
            className={field}
          />
        </label>
        {view !== "representative" && reps ? (
          <label className="col-span-2 block text-sm font-medium text-slate-700 md:col-span-1">
            Sales rep
            <select name="rep" defaultValue={filters.rep} className={field}>
              <option value="">Whole team</option>
              {reps.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.display_name}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <span className="hidden md:block" />
        )}
        <div className="col-span-2 flex gap-2 md:col-span-1">
          <button type="submit" className={buttonClass()}>
            Apply
          </button>
          <Link
            href={dashboardHref(filters, { range: "30d", rep: "" })}
            className={buttonClass("secondary")}
          >
            Reset
          </Link>
        </div>
      </form>
      <p className="mt-3 text-xs text-slate-500">
        Pick <strong>Custom dates</strong> to use From/To. Showing{" "}
        <span data-testid="dashboard-period">
          {formatPeriod(filters.start, filters.end)}
        </span>{" "}
        (UTC). Figures marked “now” are current and ignore the period.
      </p>
    </Card>
  );
}

// --- Building blocks -----------------------------------------------------------------------------

function Tile({
  label,
  value,
  hint,
  href,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  href?: string;
}) {
  return (
    <Card className="p-5">
      <dt className="text-sm font-medium text-slate-600">{label}</dt>
      <dd className="mt-2 text-2xl font-semibold tracking-tight text-slate-900">
        {href ? (
          <Link href={href} className="hover:text-brand-700">
            {value}
          </Link>
        ) : (
          value
        )}
      </dd>
      {hint && <dd className="mt-1 text-xs text-slate-500">{hint}</dd>}
    </Card>
  );
}

function Section({
  title,
  description,
  children,
  action,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <Card>
      <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4">
        <div>
          <h2 className="text-base font-semibold text-slate-900">{title}</h2>
          {description && (
            <p className="mt-0.5 text-xs text-slate-500">{description}</p>
          )}
        </div>
        {action}
      </div>
      {children}
    </Card>
  );
}

/** Horizontal bar; width relative to the largest value in its group. */
function Bar({ value, max }: { value: number; max: number }) {
  const width = max > 0 ? Math.max((value / max) * 100, value > 0 ? 3 : 0) : 0;
  return (
    <div className="h-2 w-full rounded-full bg-slate-100" aria-hidden="true">
      <div
        className="h-2 rounded-full bg-brand-600"
        style={{ width: `${width}%` }}
      />
    </div>
  );
}

// --- Sales sections ------------------------------------------------------------------------------

export function SalesTiles({ data }: { data: Dashboard }) {
  const { leads, customers, pipeline, follow_ups } = data;
  return (
    <dl className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-6">
      <Tile
        label="Leads created"
        value={leads.created}
        hint={`${leads.assigned} assigned · ${leads.unassigned} unassigned`}
        href="/leads"
      />
      <Tile
        label="Qualified"
        value={leads.qualified}
        hint="of the leads created in the period"
        href="/leads?status=qualified"
      />
      <Tile
        label="Converted"
        value={leads.converted_in_period}
        hint={`in the period · conversion rate ${formatRate(leads.conversion_rate)}`}
        href="/leads?status=converted"
      />
      <Tile
        label="Customers"
        value={customers.total}
        hint={`${customers.active} active · ${customers.new_in_period} new in period`}
        href="/accounts"
      />
      <Tile
        label="Open opportunities (now)"
        value={pipeline.open_count}
        hint={formatAmounts(pipeline.open_value)}
      />
      <Tile
        label="Follow-ups due (now)"
        value={follow_ups.total}
        hint={`${leads.open_now} open leads in total`}
      />
    </dl>
  );
}

const FUNNEL: {
  key: "new" | "contacted" | "qualified" | "unqualified" | "converted";
  label: string;
}[] = [
  { key: "new", label: "New" },
  { key: "contacted", label: "Contacted" },
  { key: "qualified", label: "Qualified" },
  { key: "converted", label: "Converted" },
  { key: "unqualified", label: "Unqualified" },
];

export function LeadFunnel({ data }: { data: Dashboard }) {
  const max = Math.max(...FUNNEL.map((s) => data.leads[s.key]));
  return (
    <Section
      title="Leads by status"
      description="Current status of the leads created in the period"
    >
      {data.leads.created === 0 ? (
        <EmptyState
          title="No leads in this period"
          description="Try a longer period."
        />
      ) : (
        <ul className="space-y-3 px-5 py-4">
          {FUNNEL.map((s) => (
            <li
              key={s.key}
              className="grid grid-cols-[7rem_1fr_3rem] items-center gap-3 text-sm"
            >
              <span className="text-slate-700">{s.label}</span>
              <Bar value={data.leads[s.key]} max={max} />
              <span className="text-right font-medium text-slate-900">
                {data.leads[s.key]}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

export function PipelineByStage({ data }: { data: Dashboard }) {
  const { pipeline } = data;
  const max = Math.max(...pipeline.by_stage.map((s) => s.count));
  return (
    <Section
      title="Open pipeline by stage (now)"
      description={`${pipeline.closing_in_period} expected to close in the period (${formatAmounts(pipeline.closing_in_period_value)})${pipeline.without_amount ? ` · ${pipeline.without_amount} without an amount` : ""}`}
    >
      {pipeline.open_count === 0 ? (
        <EmptyState
          title="No open opportunities"
          description="Opportunities are created when a lead is converted."
        />
      ) : (
        <ul className="space-y-3 px-5 py-4">
          {pipeline.by_stage.map((s) => (
            <li
              key={s.stage}
              className="grid grid-cols-[7rem_1fr_3rem] items-center gap-3 text-sm"
            >
              <span className="text-slate-700">
                {STAGE_LABELS[s.stage] ?? s.stage}
              </span>
              <div>
                <Bar value={s.count} max={max} />
                <p className="mt-1 text-xs text-slate-500">
                  {formatAmounts(s.value)}
                </p>
              </div>
              <span className="text-right font-medium text-slate-900">
                {s.count}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

export function FollowUpList({ data }: { data: Dashboard }) {
  const { follow_ups } = data;
  return (
    <Section
      title="Pending follow-ups"
      description={`${follow_ups.rule}. Oldest first.`}
      action={
        follow_ups.total > follow_ups.items.length && (
          <span className="text-xs text-slate-500">
            {follow_ups.items.length} of {follow_ups.total}
          </span>
        )
      }
    >
      {follow_ups.items.length === 0 ? (
        <EmptyState
          title="Nothing to follow up"
          description="Every open lead had activity in the last 7 days."
        />
      ) : (
        <ul className="divide-y divide-slate-100">
          {follow_ups.items.map((f) => (
            <li
              key={f.lead_id}
              className="flex items-center justify-between gap-4 px-5 py-3"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-slate-900">
                  <Link
                    href={`/leads/${f.lead_id}`}
                    className="hover:text-brand-700 hover:underline"
                  >
                    {f.name}
                  </Link>
                </p>
                <p className="truncate text-xs text-slate-500">
                  {f.company ?? "No company"} · {f.owner_name ?? "No owner"} ·{" "}
                  <span className="font-medium text-amber-700">
                    {f.days_idle} days without activity
                  </span>
                </p>
              </div>
              <StatusBadge status={f.status} />
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

export function ActivityFeed({ data }: { data: Dashboard }) {
  return (
    <Section
      title="Recent customer activity"
      description="Lead activity, new support tickets and order events in the period"
    >
      {data.recent_activities.length === 0 ? (
        <EmptyState title="No activity in this period" />
      ) : (
        <ol className="divide-y divide-slate-100">
          {data.recent_activities.map((a) => (
            <li key={`${a.kind}-${a.record_id}-${a.at}`} className="px-5 py-3">
              <p className="text-sm font-medium text-slate-900">
                <Link
                  href={recordHref(a.record_type, a.record_id)}
                  className="hover:text-brand-700 hover:underline"
                >
                  {a.title}
                </Link>
              </p>
              <p className="text-xs text-slate-500">
                {formatDateTime(a.at)}
                {a.actor_name && ` · ${a.actor_name}`}
                {a.detail && ` · ${a.detail}`}
              </p>
            </li>
          ))}
        </ol>
      )}
    </Section>
  );
}

export function TeamTable({
  data,
  filters,
}: {
  data: Dashboard;
  filters: DashboardFilters;
}) {
  if (!data.team) return null;
  return (
    <Section
      title="Sales team"
      description="Per sales rep. Leads, qualified and converted are for the period; customers, opportunities and follow-ups are now."
    >
      {data.team.length === 0 ? (
        <EmptyState
          title="No sales reps yet"
          description="Give colleagues the sales agent or sales manager role on the Users page."
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-600">
              <tr>
                <th scope="col" className="px-5 py-3">
                  Sales rep
                </th>
                <th scope="col" className="px-3 py-3 text-right">
                  Leads
                </th>
                <th scope="col" className="px-3 py-3 text-right">
                  Qualified
                </th>
                <th scope="col" className="px-3 py-3 text-right">
                  Converted
                </th>
                <th scope="col" className="px-3 py-3 text-right">
                  Customers
                </th>
                <th scope="col" className="px-3 py-3 text-right">
                  Open opps
                </th>
                <th scope="col" className="px-3 py-3 text-right">
                  Open value
                </th>
                <th scope="col" className="px-5 py-3 text-right">
                  Follow-ups
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.team.map((row) => (
                <tr key={row.user_id ?? "none"}>
                  <th
                    scope="row"
                    className="px-5 py-3 text-left font-medium text-slate-900"
                  >
                    {row.user_id && !filters.rep ? (
                      <Link
                        href={dashboardHref(filters, { rep: row.user_id })}
                        className="hover:text-brand-700 hover:underline"
                        aria-label={`Show the dashboard for ${row.name}`}
                      >
                        {row.name}
                      </Link>
                    ) : (
                      <span
                        className={
                          row.user_id ? undefined : "italic text-slate-500"
                        }
                      >
                        {row.name}
                      </span>
                    )}
                  </th>
                  <td className="px-3 py-3 text-right">{row.leads_created}</td>
                  <td className="px-3 py-3 text-right">{row.qualified}</td>
                  <td className="px-3 py-3 text-right">
                    {row.converted_in_period}
                  </td>
                  <td className="px-3 py-3 text-right">{row.customers}</td>
                  <td className="px-3 py-3 text-right">
                    {row.open_opportunities}
                  </td>
                  <td className="px-3 py-3 text-right whitespace-nowrap">
                    {formatAmounts(row.open_value)}
                  </td>
                  <td className="px-5 py-3 text-right">{row.follow_ups}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}

// --- Executive -------------------------------------------------------------------------------------

export function ExecutiveTiles({ data }: { data: Dashboard }) {
  const { revenue, orders, support } = data;
  if (!revenue || !orders || !support) return null;
  return (
    <section aria-labelledby="business-heading" className="mb-6">
      <h2
        id="business-heading"
        className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500"
      >
        Business
      </h2>
      <dl className="grid grid-cols-2 gap-4 lg:grid-cols-4 xl:grid-cols-7">
        <Tile
          label="Invoiced"
          value={formatAmounts(revenue.issued_value)}
          hint={`${revenue.issued_count} invoices issued in the period`}
          href="/invoices"
        />
        <Tile
          label="Payments received"
          value={formatAmounts(revenue.received)}
          hint="in the period, after reversals"
        />
        <Tile
          label="Outstanding (now)"
          value={formatAmounts(revenue.outstanding)}
          hint={`${revenue.outstanding_count} unpaid invoices`}
        />
        <Tile
          label="Overdue (now)"
          value={formatAmounts(revenue.overdue)}
          hint={`${revenue.overdue_count} past their due date`}
        />
        <Tile
          label="Orders confirmed"
          value={orders.confirmed_in_period}
          hint={`${formatAmounts(orders.confirmed_value)} · ${orders.in_progress_now} in progress now`}
          href="/orders"
        />
        <Tile
          label="Open tickets (now)"
          value={support.open_now}
          hint={`${support.sla_overdue_now} past SLA · ${support.opened_in_period} opened · ${support.complaints_in_period} complaints in period`}
          href="/tickets"
        />
        <Tile
          label="Customer satisfaction"
          value={
            support.average_rating === null
              ? "—"
              : `${support.average_rating.toFixed(1)} / 5`
          }
          hint={`${support.ratings_in_period} rating${support.ratings_in_period === 1 ? "" : "s"} in the period`}
        />
      </dl>
    </section>
  );
}
