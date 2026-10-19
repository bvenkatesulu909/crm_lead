import type { Metadata } from "next";
import Link from "next/link";

import {
  Card,
  EmptyState,
  ErrorAlert,
  Forbidden,
  PageHeader,
  buttonClass,
  cx,
} from "@/components/ui";
import { ApiError, toErrorInfo } from "@/lib/api-error";
import type { DirectoryUser, HealthOverview } from "@/lib/api-types";
import { HEALTH_LABELS, LIFECYCLE_LABELS } from "@/lib/customer-data";
import { hasAny } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

export const metadata: Metadata = { title: "Customer health" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const STYLE = {
  healthy: "bg-emerald-50 text-emerald-800",
  watch: "bg-amber-50 text-amber-800",
  at_risk: "bg-red-50 text-red-800",
} as const;

export default async function CustomerHealthPage({
  searchParams,
}: PageProps<"/accounts/health">) {
  const { owner } = await searchParams;
  const ownerId = typeof owner === "string" && UUID.test(owner) ? owner : "";
  const me = await getMe();
  const everyone = hasAny(me, "account:read:all");

  let data: HealthOverview;
  let people: DirectoryUser[];
  try {
    [data, people] = await Promise.all([
      apiFetch<HealthOverview>(
        `/customer-health?limit=500${ownerId ? `&owner_id=${ownerId}` : ""}`,
      ),
      apiFetch<DirectoryUser[]>("/users").catch(() => []),
    ]);
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) return <Forbidden />;
    return (
      <ErrorAlert
        title="Customer health could not be loaded"
        error={toErrorInfo(error)}
      />
    );
  }
  const name = (id: string | null) =>
    id
      ? (people.find((p) => p.id === id)?.display_name ?? "Former colleague")
      : "Nobody";
  const tiles: [string, number, string][] = [
    ["At risk", data.at_risk, "text-red-700"],
    ["Watch", data.watch, "text-amber-700"],
    ["Healthy", data.healthy, "text-emerald-700"],
    ["Inactive 90+ days", data.inactive, "text-slate-900"],
  ];

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link href="/accounts" className="font-medium text-brand-700 hover:underline">← Accounts</Link>
      </nav>
      <PageHeader
        title="Customer health"
        description="Customers that need attention first. The score starts at 100 and loses points for inactivity, overdue invoices, late tickets, complaints and low satisfaction - every factor is shown on the customer's page."
      />
      {everyone && (
        <Card className="mb-6">
          <form className="flex flex-wrap items-end gap-3 px-5 py-4" aria-label="Filter customer health">
            <label className="text-sm font-medium text-slate-700">
              Owner
              <select name="owner" defaultValue={ownerId}
                className="mt-1 block rounded-md border-0 bg-white px-3 py-2 text-sm ring-1 ring-inset ring-slate-300">
                <option value="">Everyone</option>
                {people.filter((p) => p.assignable).map((p) => <option key={p.id} value={p.id}>{p.display_name}</option>)}
              </select>
            </label>
            <button type="submit" className={buttonClass("primary")}>Apply</button>
          </form>
        </Card>
      )}
      <dl className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        {tiles.map(([label, value, colour]) => (
          <Card key={label} className="p-5">
            <dt className="text-sm font-medium text-slate-600">{label}</dt>
            <dd className={cx("mt-2 text-2xl font-semibold", colour)}>{value}</dd>
          </Card>
        ))}
      </dl>
      <Card>
        {data.items.length === 0 ? (
          <EmptyState title="No customers to assess" />
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <caption className="sr-only">Customers, least healthy first</caption>
              <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-600">
                <tr>
                  <th scope="col" className="px-5 py-3">Customer</th>
                  <th scope="col" className="px-5 py-3">Health</th>
                  <th scope="col" className="hidden px-5 py-3 md:table-cell">Main reason</th>
                  <th scope="col" className="hidden px-5 py-3 sm:table-cell">Last interaction</th>
                  <th scope="col" className="hidden px-5 py-3 lg:table-cell">Lifecycle</th>
                  <th scope="col" className="hidden px-5 py-3 lg:table-cell">Owner</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {data.items.map((row) => (
                  <tr key={row.account_id}>
                    <th scope="row" className="px-5 py-3 text-left font-medium">
                      <Link href={`/accounts/${row.account_id}`} className="text-brand-700 hover:underline">{row.name}</Link>
                    </th>
                    <td className="px-5 py-3">
                      <span className={cx("rounded-full px-2.5 py-0.5 text-xs font-semibold", STYLE[row.label])}>
                        {HEALTH_LABELS[row.label]} · {row.score}
                      </span>
                    </td>
                    <td className="hidden px-5 py-3 text-slate-700 md:table-cell">{row.top_factor ?? "—"}</td>
                    <td className="hidden px-5 py-3 text-slate-700 sm:table-cell">
                      {row.days_inactive === null ? "Never" : `${row.days_inactive} days ago`}
                      {row.inactive && <span className="ml-2 rounded bg-amber-100 px-1.5 text-xs text-amber-900">Inactive</span>}
                    </td>
                    <td className="hidden px-5 py-3 text-slate-700 lg:table-cell">
                      {row.lifecycle_stage ? LIFECYCLE_LABELS[row.lifecycle_stage] : "—"}
                    </td>
                    <td className="hidden px-5 py-3 text-slate-700 lg:table-cell">{name(row.owner_id)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="border-t border-slate-100 px-5 py-2 text-xs text-slate-500">
          Up to 500 customers you may see are assessed. Renewal alerts come with contracts (a later phase).
        </p>
      </Card>
    </>
  ); // prettier-ignore
}
