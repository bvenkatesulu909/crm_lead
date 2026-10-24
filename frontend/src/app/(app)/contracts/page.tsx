import type { Metadata } from "next";
import Link from "next/link";

import { ContractStatusBadge, EndHint } from "@/components/contract-view";
import { Pagination } from "@/components/pagination";
import {
  ButtonLink,
  Card,
  EmptyState,
  ErrorAlert,
  Forbidden,
  PageHeader,
  buttonClass,
} from "@/components/ui";
import { ApiError, toErrorInfo } from "@/lib/api-error";
import { CONTRACT_STATUSES, type ContractPage } from "@/lib/api-types";
import { CONTRACT_STATUS_LABELS } from "@/lib/contracts";
import { formatAmounts } from "@/lib/dashboard";
import { formatDate } from "@/lib/format";
import { canWriteContracts, hasAny } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

export const metadata: Metadata = { title: "Contracts" };

const PAGE_SIZE = 25;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ENDING = ["30", "60", "90"] as const;
const field =
  "mt-1 block w-full rounded-md border-0 bg-white px-3 py-2 text-sm text-slate-900 ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-brand-600";

export default async function ContractsPage({
  searchParams,
}: PageProps<"/contracts">) {
  const raw = await searchParams;
  const one = (v: string | string[] | undefined) =>
    (Array.isArray(v) ? v[0] : v) ?? "";
  const q = one(raw.q).trim().slice(0, 100);
  const status = (CONTRACT_STATUSES as readonly string[]).includes(
    one(raw.status),
  )
    ? one(raw.status)
    : "";
  const ending = (ENDING as readonly string[]).includes(one(raw.ending))
    ? one(raw.ending)
    : "";
  const account = UUID.test(one(raw.account_id)) ? one(raw.account_id) : "";
  const pageNumber = Math.min(
    Math.max(Number.parseInt(one(raw.page), 10) || 1, 1),
    5000,
  );
  const me = await getMe();
  const query = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String((pageNumber - 1) * PAGE_SIZE),
  });
  if (q) query.set("q", q);
  if (status) query.set("status", status);
  if (ending) query.set("ending_within_days", ending);
  if (account) query.set("account_id", account);

  let data: ContractPage;
  try {
    data = await apiFetch<ContractPage>(`/contracts?${query}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) return <Forbidden />;
    return (
      <ErrorAlert
        title="Contracts could not be loaded"
        error={toErrorInfo(error)}
      />
    );
  }
  const href = (page: number) => {
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    if (status) p.set("status", status);
    if (ending) p.set("ending", ending);
    if (account) p.set("account_id", account);
    if (page > 1) p.set("page", String(page));
    return p.toString() ? `/contracts?${p}` : "/contracts";
  };
  const filtered = q || status || ending || account;

  return (
    <>
      <PageHeader
        title="Contracts"
        description={hasAny(me, "contract:read:all") ? "All contracts of your organisation, with their renewal dates." : "Your contracts and contracts of your customers."}
        actions={canWriteContracts(me) && <ButtonLink href={account ? `/contracts/new?account=${account}` : "/contracts/new"}>New contract</ButtonLink>}
      />
      {account && (
        <p className="mb-4 text-sm text-slate-700">
          Showing the contracts of one account.{" "}
          <Link href="/contracts" className="font-medium text-brand-700 hover:underline">Show all contracts</Link>
        </p>
      )}
      <Card>
        <form role="search" aria-label="Filter contracts" className="grid gap-4 px-5 py-4 sm:grid-cols-[2fr_1fr_1fr_auto]">
          <div>
            <label htmlFor="contract-q" className="text-sm font-medium text-slate-700">Search</label>
            <input id="contract-q" name="q" type="search" defaultValue={q} maxLength={100} placeholder="Title or number (CT-0007)" className={field} />
          </div>
          <div>
            <label htmlFor="contract-status" className="text-sm font-medium text-slate-700">Status</label>
            <select id="contract-status" name="status" defaultValue={status} className={field}>
              <option value="">All statuses</option>
              {CONTRACT_STATUSES.map((s) => <option key={s} value={s}>{CONTRACT_STATUS_LABELS[s]}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="contract-ending" className="text-sm font-medium text-slate-700">Ending</label>
            <select id="contract-ending" name="ending" defaultValue={ending} className={field}>
              <option value="">Any time</option>
              {ENDING.map((d) => <option key={d} value={d}>Within {d} days</option>)}
            </select>
          </div>
          <div className="flex items-end gap-2">
            {account && <input type="hidden" name="account_id" value={account} />}
            <button type="submit" className={buttonClass("primary")}>Apply</button>
            {(q || status || ending) && <Link href={account ? `/contracts?account_id=${account}` : "/contracts"} className={buttonClass("secondary")}>Clear</Link>}
          </div>
        </form>
        <div className="border-t border-slate-200">
          {data.items.length === 0 ? (
            <EmptyState
              title={filtered ? "No contracts match" : "No contracts yet"}
              description={filtered ? "Try other filters." : "Record the agreements your customers have signed, to keep track of their renewals."}
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200 text-sm">
                <caption className="sr-only">Contracts, page {pageNumber}</caption>
                <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-600">
                  <tr>
                    <th scope="col" className="px-5 py-3">Contract</th>
                    <th scope="col" className="px-5 py-3">Account</th>
                    <th scope="col" className="px-5 py-3">Status</th>
                    <th scope="col" className="px-5 py-3 text-right">Value</th>
                    <th scope="col" className="hidden px-5 py-3 md:table-cell">Ends</th>
                    <th scope="col" className="hidden px-5 py-3 lg:table-cell">Owner</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {data.items.map((c) => (
                    <tr key={c.id}>
                      <th scope="row" className="px-5 py-3 text-left font-medium">
                        <Link href={`/contracts/${c.id}`} className="text-brand-700 hover:underline">
                          <span className="font-mono text-xs text-slate-500">{c.label}</span> {c.title}
                        </Link>
                      </th>
                      <td className="px-5 py-3 text-slate-700">{c.account_name ?? "Account"}</td>
                      <td className="px-5 py-3"><ContractStatusBadge status={c.status} /></td>
                      <td className="px-5 py-3 text-right whitespace-nowrap">{formatAmounts([{ currency: c.currency, amount: c.total_value }])}</td>
                      <td className="hidden px-5 py-3 text-slate-700 md:table-cell">
                        {c.end_date ? formatDate(c.end_date) : "—"}
                        <span className="ml-2"><EndHint status={c.status} daysToEnd={c.days_to_end} /></span>
                      </td>
                      <td className="hidden px-5 py-3 text-slate-700 lg:table-cell">{c.owner_name ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        {data.total > 0 && (
          <div className="border-t border-slate-200">
            <Pagination total={data.total} page={pageNumber} pageSize={PAGE_SIZE} hrefForPage={href} />
          </div>
        )}
      </Card>
    </>
  ); // prettier-ignore
}
