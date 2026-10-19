import type { Metadata } from "next";
import Link from "next/link";

import { PaymentStateBadge, invoiceNumber } from "@/components/invoices";
import { formatMoney } from "@/components/orders";
import { Pagination } from "@/components/pagination";
import {
  Card,
  EmptyState,
  ErrorAlert,
  Forbidden,
  PageHeader,
  buttonClass,
} from "@/components/ui";
import { ApiError, toErrorInfo } from "@/lib/api-error";
import {
  INVOICE_FILTERS,
  type AccountPage,
  type InvoiceFilter,
  type InvoicePage,
} from "@/lib/api-types";
import { formatDate } from "@/lib/format";
import { canReadAccounts, hasAny } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

export const metadata: Metadata = { title: "Invoices" };

const PAGE_SIZE = 20;
const field =
  "mt-1 block w-full rounded-md border-0 bg-white px-3 py-2 text-sm text-slate-900 ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-brand-600";
const FILTER_LABELS: Record<InvoiceFilter, string> = {
  unpaid: "Unpaid",
  overdue: "Overdue",
  paid: "Paid",
  draft: "Drafts",
  discarded: "Discarded",
};

type Raw = Record<string, string | string[] | undefined>;
const one = (v: string | string[] | undefined) =>
  (Array.isArray(v) ? v[0] : v) ?? "";

function parse(raw: Raw) {
  const state = one(raw.state);
  const page = Number.parseInt(one(raw.page), 10);
  return {
    q: one(raw.q).trim().slice(0, 100),
    state: (INVOICE_FILTERS as readonly string[]).includes(state) ? state : "",
    page: Number.isFinite(page) && page > 0 && page <= 5000 ? page : 1,
  };
}
type Params = ReturnType<typeof parse>;

function href(p: Params, page: number) {
  const q = new URLSearchParams();
  if (p.q) q.set("q", p.q);
  if (p.state) q.set("state", p.state);
  if (page > 1) q.set("page", String(page));
  const s = q.toString();
  return s ? `/invoices?${s}` : "/invoices";
}

export default async function InvoicesPage({
  searchParams,
}: PageProps<"/invoices">) {
  const p = parse(await searchParams);
  const me = await getMe();
  const query = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String((p.page - 1) * PAGE_SIZE),
  });
  if (p.q) query.set("q", p.q);
  if (p.state) query.set("state", p.state);

  let data: InvoicePage;
  let accounts: AccountPage["items"] = [];
  try {
    [data, accounts] = await Promise.all([
      apiFetch<InvoicePage>(`/invoices?${query}`),
      canReadAccounts(me)
        ? apiFetch<AccountPage>("/accounts?limit=200").then((a) => a.items)
        : Promise.resolve([]),
    ]);
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) return <Forbidden />;
    return (
      <>
        <PageHeader title="Invoices" />
        <ErrorAlert
          title="Invoices could not be loaded"
          error={toErrorInfo(error)}
        />
      </>
    );
  }
  const accountName = (id: string) =>
    accounts.find((a) => a.id === id)?.name ?? "Customer account";
  const filtered = Boolean(p.q || p.state);

  return (
    <>
      <PageHeader
        title="Invoices"
        description={
          (hasAny(me, "invoice:read:all") ? "All invoices of your organisation." : "Invoices of the customers you own.") +
          " Invoices are created from confirmed orders."
        }
      />
      <Card>
        <form role="search" aria-label="Filter invoices" className="grid gap-4 px-5 py-4 sm:grid-cols-[2fr_1fr_auto]">
          <div>
            <label htmlFor="i-q" className="text-sm font-medium text-slate-700">Search</label>
            <input id="i-q" name="q" type="search" defaultValue={p.q} maxLength={100} placeholder="INV-number or customer reference" className={field} />
          </div>
          <div>
            <label htmlFor="i-state" className="text-sm font-medium text-slate-700">Show</label>
            <select id="i-state" name="state" defaultValue={p.state} className={field}>
              <option value="">All invoices</option>
              {INVOICE_FILTERS.map((s) => <option key={s} value={s}>{FILTER_LABELS[s]}</option>)}
            </select>
          </div>
          <div className="flex items-end gap-2">
            <button type="submit" className={buttonClass("primary")}>Apply</button>
            {filtered && <Link href="/invoices" className={buttonClass("secondary")}>Clear</Link>}
          </div>
        </form>
        <div className="border-t border-slate-200">
          {data.items.length === 0 ? (
            <EmptyState
              title={filtered ? "No invoices match your filters" : "No invoices yet"}
              description={filtered ? "Try other filters." : "Open a confirmed order and choose “Create invoice”."}
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200 text-sm">
                <caption className="sr-only">Invoices, page {p.page}</caption>
                <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-600">
                  <tr>
                    <th scope="col" className="px-5 py-3">Invoice</th>
                    <th scope="col" className="hidden px-5 py-3 md:table-cell">Account</th>
                    <th scope="col" className="px-5 py-3">State</th>
                    <th scope="col" className="hidden px-5 py-3 text-right sm:table-cell">Total</th>
                    <th scope="col" className="px-5 py-3 text-right">Amount due</th>
                    <th scope="col" className="hidden px-5 py-3 lg:table-cell">Due date</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {data.items.map((i) => (
                    <tr key={i.id} className="hover:bg-slate-50">
                      <th scope="row" className="px-5 py-3 text-left font-medium">
                        <Link href={`/invoices/${i.id}`} className="font-mono text-brand-700 hover:underline">{invoiceNumber(i.number)}</Link>
                      </th>
                      <td className="hidden px-5 py-3 text-slate-700 md:table-cell">{accountName(i.account_id)}</td>
                      <td className="px-5 py-3"><PaymentStateBadge state={i.payment_state} /></td>
                      <td className="hidden whitespace-nowrap px-5 py-3 text-right tabular-nums sm:table-cell">{formatMoney(i.total, i.currency)}</td>
                      <td className="whitespace-nowrap px-5 py-3 text-right tabular-nums">{formatMoney(i.balance_due, i.currency)}</td>
                      <td className="hidden whitespace-nowrap px-5 py-3 text-slate-700 lg:table-cell">{i.due_date ? formatDate(i.due_date) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        {data.total > 0 && (
          <div className="border-t border-slate-200">
            <Pagination total={data.total} page={p.page} pageSize={PAGE_SIZE} hrefForPage={(page) => href(p, page)} />
          </div>
        )}
      </Card>
    </>
  ); // prettier-ignore
}
