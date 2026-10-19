import Link from "next/link";

import { STATUS_LABELS, buttonClass } from "@/components/ui";
import { LEAD_SORTS, LEAD_SOURCES, LEAD_STATUSES } from "@/lib/api-types";
import { SOURCE_LABELS } from "@/lib/format";

import { hasFilters, type LeadListParams } from "./list-params";

const field =
  "mt-1 block w-full rounded-md border-0 bg-white px-3 py-2 text-sm text-slate-900 ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-brand-600";

/** Search + filters as a normal GET form: submitting updates the URL (and works without JS). */
export function LeadFilters({ params }: { params: LeadListParams }) {
  return (
    <form
      role="search"
      aria-label="Filter leads"
      className="grid gap-4 px-5 py-4 sm:grid-cols-2 lg:grid-cols-[2fr_1fr_1fr_1fr_auto]"
    >
      <div>
        <label htmlFor="lead-q" className="text-sm font-medium text-slate-700">
          Search
        </label>
        <input
          id="lead-q"
          name="q"
          type="search"
          defaultValue={params.q}
          maxLength={100}
          placeholder="Name, company or e-mail"
          className={field}
        />
      </div>
      <div>
        <label
          htmlFor="lead-status"
          className="text-sm font-medium text-slate-700"
        >
          Status
        </label>
        <select
          id="lead-status"
          name="status"
          defaultValue={params.status}
          className={field}
        >
          <option value="">All statuses</option>
          {LEAD_STATUSES.map((s) => (
            <option key={s} value={s}>
              {STATUS_LABELS[s]}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label
          htmlFor="lead-source"
          className="text-sm font-medium text-slate-700"
        >
          Source
        </label>
        <select
          id="lead-source"
          name="source"
          defaultValue={params.source}
          className={field}
        >
          <option value="">All sources</option>
          {LEAD_SOURCES.map((s) => (
            <option key={s} value={s}>
              {SOURCE_LABELS[s]}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label
          htmlFor="lead-priority"
          className="text-sm font-medium text-slate-700"
        >
          Priority
        </label>
        <select
          id="lead-priority"
          name="priority"
          defaultValue={params.priority}
          className={field}
        >
          <option value="">Any score</option>
          <option value="hot">Hot (70+)</option>
          <option value="warm">Warm (40–69)</option>
          <option value="cold">Cold (under 40)</option>
        </select>
      </div>
      <div>
        <label
          htmlFor="lead-sort"
          className="text-sm font-medium text-slate-700"
        >
          Sort by
        </label>
        <select
          id="lead-sort"
          name="sort"
          defaultValue={params.sort}
          className={field}
        >
          {Object.entries(LEAD_SORTS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <div className="flex items-end gap-2">
        <button type="submit" className={buttonClass("primary")}>
          Apply
        </button>
        {hasFilters(params) && (
          <Link href="/leads" className={buttonClass("secondary")}>
            Clear
          </Link>
        )}
      </div>
    </form>
  );
}
