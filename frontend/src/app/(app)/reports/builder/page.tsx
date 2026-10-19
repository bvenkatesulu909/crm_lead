import type { Metadata } from "next";
import Link from "next/link";

import { ReportTableView } from "@/components/report-table";
import {
  Card,
  ErrorAlert,
  Forbidden,
  PageHeader,
  buttonClass,
} from "@/components/ui";
import { ApiError, toErrorInfo } from "@/lib/api-error";
import type {
  DirectoryUser,
  ReportCatalogue,
  ReportTable,
} from "@/lib/api-types";
import { canUseReports } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";
import { optionLabel } from "@/lib/workflows";

export const metadata: Metadata = { title: "Report builder" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const field =
  "mt-1 block w-full rounded-md border-0 bg-white px-3 py-2 text-sm text-slate-900 ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-brand-600";

/** Pick a record type, columns and filters: see a preview and download everything as CSV. */
export default async function BuilderPage({
  searchParams,
}: PageProps<"/reports/builder">) {
  const raw = await searchParams;
  const one = (v: string | string[] | undefined) =>
    (Array.isArray(v) ? v[0] : v) ?? "";
  const me = await getMe();
  if (!canUseReports(me)) return <Forbidden />;
  const catalogue = await apiFetch<ReportCatalogue>("/reports");
  const type =
    catalogue.record_types.find((t) => t.key === one(raw.type)) ??
    catalogue.record_types[0];
  if (!type)
    return <Forbidden message="Your role has no record lists to export." />;

  const columnsRaw =
    raw.columns === undefined
      ? []
      : Array.isArray(raw.columns)
        ? raw.columns
        : [raw.columns];
  const columns = columnsRaw.filter((c) =>
    type.columns.some((x) => x.key === c),
  );
  const start = DAY.test(one(raw.start)) ? one(raw.start) : "";
  const end = DAY.test(one(raw.end)) ? one(raw.end) : "";
  const owner =
    UUID.test(one(raw.owner_id)) && catalogue.can_filter_by_rep
      ? one(raw.owner_id)
      : "";
  const status = type.statuses.includes(one(raw.status)) ? one(raw.status) : "";

  const query = new URLSearchParams();
  for (const c of columns) query.append("columns", c);
  for (const [name, value] of [
    ["start", start],
    ["end", end],
    ["owner_id", owner],
    ["status", status],
  ])
    if (value) query.set(name, value);
  const reps = catalogue.can_filter_by_rep
    ? await apiFetch<DirectoryUser[]>("/users?assignable=true").catch(() => [])
    : [];

  let table: ReportTable | null = null;
  let problem: ReturnType<typeof toErrorInfo> | null = null;
  try {
    table = await apiFetch<ReportTable>(
      `/reports/builder/${type.key}?${query}&limit=50`,
    );
  } catch (error) {
    if (
      error instanceof ApiError &&
      (error.status === 422 || error.status === 403)
    )
      problem = toErrorInfo(error);
    else throw error;
  }
  const csv = new URLSearchParams(query);
  csv.set("type", type.key);

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link href="/reports" className="font-medium text-brand-700 hover:underline">← Reports</Link>
      </nav>
      <PageHeader title="Report builder" description="Choose what to list. Only records you may see are included; CSV downloads are recorded in the audit log." />
      <div className="grid gap-6 lg:grid-cols-4">
        <Card className="self-start p-5 lg:col-span-1">
          <form role="search" aria-label="Builder" className="space-y-4">
            <div><label htmlFor="b-type" className="text-sm font-medium text-slate-700">Records</label>
              <select id="b-type" name="type" defaultValue={type.key} className={field}>
                {catalogue.record_types.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
              </select>
              <p className="mt-1 text-xs text-slate-500">Changing the type? Press Apply, then choose columns.</p></div>
            <fieldset><legend className="text-sm font-medium text-slate-700">Columns</legend>
              <ul className="mt-1 space-y-1">
                {type.columns.map((c) => (
                  <li key={c.key}><label className="flex items-center gap-2 text-sm text-slate-700">
                    <input type="checkbox" name="columns" value={c.key} defaultChecked={columns.length === 0 || columns.includes(c.key)} className="h-4 w-4 rounded border-slate-300 text-brand-600" />{c.label}</label></li>
                ))}
              </ul></fieldset>
            <div><label htmlFor="b-start" className="text-sm font-medium text-slate-700">Created from</label>
              <input id="b-start" type="date" name="start" defaultValue={start} className={field} /></div>
            <div><label htmlFor="b-end" className="text-sm font-medium text-slate-700">Created until</label>
              <input id="b-end" type="date" name="end" defaultValue={end} className={field} /></div>
            {type.statuses.length > 0 && (
              <div><label htmlFor="b-status" className="text-sm font-medium text-slate-700">Status</label>
                <select id="b-status" name="status" defaultValue={status} className={field}>
                  <option value="">Any</option>
                  {type.statuses.map((s) => <option key={s} value={s}>{optionLabel(s)}</option>)}
                </select></div>
            )}
            {catalogue.can_filter_by_rep && (
              <div><label htmlFor="b-rep" className="text-sm font-medium text-slate-700">Owner</label>
                <select id="b-rep" name="owner_id" defaultValue={owner} className={field}>
                  <option value="">Everyone</option>
                  {reps.map((p) => <option key={p.id} value={p.id}>{p.display_name}</option>)}
                </select></div>
            )}
            <div className="flex flex-wrap gap-2">
              <button type="submit" className={buttonClass("primary")}>Apply</button>
              {table && <a href={`/reports/builder/csv?${csv}`} download className={buttonClass("secondary")}>Download CSV</a>}
            </div>
          </form>
        </Card>
        <Card className="lg:col-span-3" aria-labelledby="preview-heading">
          <h2 id="preview-heading" className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">Preview (first 50 rows)</h2>
          {problem && <div className="p-4"><ErrorAlert title="This list could not be shown" error={problem} /></div>}
          {table && <ReportTableView table={table} />}
        </Card>
      </div>
    </>
  ); // prettier-ignore
}
