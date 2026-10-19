import type { Metadata } from "next";
import Link from "next/link";

import { ReportTableView } from "@/components/report-table";
import {
  ButtonLink,
  Card,
  ErrorAlert,
  Forbidden,
  PageHeader,
  buttonClass,
  cx,
} from "@/components/ui";
import { ApiError, toErrorInfo } from "@/lib/api-error";
import type { DirectoryUser, Report, ReportCatalogue } from "@/lib/api-types";
import { canUseReports } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

export const metadata: Metadata = { title: "Reports" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const field =
  "mt-1 block w-full rounded-md border-0 bg-white px-3 py-2 text-sm text-slate-900 ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-brand-600";

/** Standard reports with a period (and, for managers, a sales rep) - each downloadable as CSV. */
export default async function ReportsPage({
  searchParams,
}: PageProps<"/reports">) {
  const raw = await searchParams;
  const one = (v: string | string[] | undefined) =>
    (Array.isArray(v) ? v[0] : v) ?? "";
  const me = await getMe();
  if (!canUseReports(me)) return <Forbidden />;
  const catalogue = await apiFetch<ReportCatalogue>("/reports");
  const key =
    catalogue.reports.find((r) => r.key === one(raw.report))?.key ??
    catalogue.reports[0]?.key;
  const start = DAY.test(one(raw.start)) ? one(raw.start) : "";
  const end = DAY.test(one(raw.end)) ? one(raw.end) : "";
  const owner = UUID.test(one(raw.owner_id)) ? one(raw.owner_id) : "";

  const query = new URLSearchParams();
  if (start) query.set("start", start);
  if (end) query.set("end", end);
  if (owner && catalogue.can_filter_by_rep) query.set("owner_id", owner);
  const reps = catalogue.can_filter_by_rep
    ? await apiFetch<DirectoryUser[]>("/users?assignable=true").catch(() => [])
    : [];

  let report: Report | null = null;
  let problem: ReturnType<typeof toErrorInfo> | null = null;
  if (key) {
    try {
      report = await apiFetch<Report>(`/reports/${key}?${query}`);
    } catch (error) {
      if (
        error instanceof ApiError &&
        (error.status === 422 || error.status === 403)
      )
        problem = toErrorInfo(error);
      else throw error;
    }
  }
  const csv = key ? `/reports/${key}/csv?${query}` : "";

  return (
    <>
      <PageHeader title="Reports" description="Figures for a period, always limited to what you may see. Download any of them as CSV."
        actions={<ButtonLink href="/reports/builder" variant="secondary">Report builder</ButtonLink>} />
      {catalogue.reports.length === 0 ? (
        <Card className="p-6 text-sm text-slate-600">No standard reports are available for your role. Try the report builder.</Card>
      ) : (
        <>
          <nav aria-label="Reports" className="mb-4 flex flex-wrap gap-2">
            {catalogue.reports.map((r) => (
              <Link key={r.key} href={`/reports?report=${r.key}${query.size ? `&${query}` : ""}`} aria-current={r.key === key ? "page" : undefined}
                className={cx("rounded-full px-3 py-1.5 text-sm font-medium", r.key === key ? "bg-brand-700 text-white" : "bg-white text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50")}>{r.title}</Link>
            ))}
          </nav>
          <Card>
            <form role="search" aria-label="Report filters" className="grid gap-4 px-5 py-4 sm:grid-cols-[1fr_1fr_1fr_auto]">
              <input type="hidden" name="report" value={key} />
              <div><label htmlFor="r-start" className="text-sm font-medium text-slate-700">From</label>
                <input id="r-start" type="date" name="start" defaultValue={report?.start ?? start} className={field} /></div>
              <div><label htmlFor="r-end" className="text-sm font-medium text-slate-700">To</label>
                <input id="r-end" type="date" name="end" defaultValue={report?.end ?? end} className={field} /></div>
              {catalogue.can_filter_by_rep ? (
                <div><label htmlFor="r-rep" className="text-sm font-medium text-slate-700">Sales rep</label>
                  <select id="r-rep" name="owner_id" defaultValue={owner} className={field}>
                    <option value="">Everyone</option>
                    {reps.map((p) => <option key={p.id} value={p.id}>{p.display_name}</option>)}
                  </select></div>
              ) : <div />}
              <div className="flex items-end gap-2">
                <button type="submit" className={buttonClass("primary")}>Apply</button>
                {csv && report && <a href={csv} download className={buttonClass("secondary")}>Download CSV</a>}
              </div>
            </form>
            {problem && <div className="border-t border-slate-200 p-4"><ErrorAlert title="This report could not be shown" error={problem} /></div>}
            {report && (
              <div className="divide-y divide-slate-200 border-t border-slate-200">
                <p className="px-5 py-2 text-xs text-slate-500">{report.start} to {report.end} (UTC). Amounts are never added across currencies.</p>
                {report.sections.map((t) => (
                  <section key={t.title} aria-label={t.title}>
                    <h2 className="px-5 pt-4 text-base font-semibold text-slate-900">{t.title}</h2>
                    <ReportTableView table={t} />
                  </section>
                ))}
              </div>
            )}
          </Card>
        </>
      )}
    </>
  ); // prettier-ignore
}
