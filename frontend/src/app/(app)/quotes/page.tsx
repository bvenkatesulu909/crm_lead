import type { Metadata } from "next";
import Link from "next/link";

import { Pagination } from "@/components/pagination";
import {
  ButtonLink,
  Card,
  EmptyState,
  ErrorAlert,
  Forbidden,
  PageHeader,
  buttonClass,
  cx,
} from "@/components/ui";
import { ApiError, toErrorInfo } from "@/lib/api-error";
import {
  QUOTE_STATUSES,
  type AccountPage,
  type QuotePage,
} from "@/lib/api-types";
import { formatAmounts } from "@/lib/dashboard";
import { formatDate } from "@/lib/format";
import { canWriteQuotes, hasAny } from "@/lib/permissions";
import {
  QUOTE_STATUS_LABELS,
  QUOTE_STATUS_STYLE,
  quoteNumber,
} from "@/lib/quotes";
import { apiFetch, getMe } from "@/lib/server/api";

export const metadata: Metadata = { title: "Quotes" };

const PAGE_SIZE = 25;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
// Links from an account, deal or order open this list filtered to that record.
const LINK_FILTERS = {
  account_id: "this account",
  opportunity_id: "this deal",
  order_id: "this order",
} as const;
const field =
  "mt-1 block w-full rounded-md border-0 bg-white px-3 py-2 text-sm text-slate-900 ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-brand-600";

export default async function QuotesPage({
  searchParams,
}: PageProps<"/quotes">) {
  const raw = await searchParams;
  const one = (v: string | string[] | undefined) =>
    (Array.isArray(v) ? v[0] : v) ?? "";
  const q = one(raw.q).trim().slice(0, 100);
  const status = (QUOTE_STATUSES as readonly string[]).includes(one(raw.status))
    ? one(raw.status)
    : "";
  const pageNumber = Math.min(
    Math.max(Number.parseInt(one(raw.page), 10) || 1, 1),
    5000,
  );
  const linked = (Object.keys(LINK_FILTERS) as (keyof typeof LINK_FILTERS)[])
    .map((key) => [key, one(raw[key])] as const)
    .find(([, value]) => UUID.test(value));
  const me = await getMe();
  const query = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String((pageNumber - 1) * PAGE_SIZE),
  });
  if (q) query.set("q", q);
  if (status) query.set("status", status);
  if (linked) {
    query.set(linked[0], linked[1]);
    query.set("include_superseded", "true");
  }

  let data: QuotePage;
  let accounts: AccountPage["items"];
  try {
    [data, accounts] = await Promise.all([
      apiFetch<QuotePage>(`/quotes?${query}`),
      apiFetch<AccountPage>("/accounts?limit=200")
        .then((a) => a.items)
        .catch(() => []),
    ]);
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) return <Forbidden />;
    return (
      <ErrorAlert
        title="Quotes could not be loaded"
        error={toErrorInfo(error)}
      />
    );
  }
  const accountName = (id: string) =>
    accounts.find((a) => a.id === id)?.name ?? "Account";
  const href = (page: number) => {
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    if (status) p.set("status", status);
    if (linked) p.set(linked[0], linked[1]);
    if (page > 1) p.set("page", String(page));
    return p.toString() ? `/quotes?${p}` : "/quotes";
  };

  return (
    <>
      <PageHeader
        title="Quotes"
        description={hasAny(me, "quote:read:all") ? "All quotes of your organisation." : "Your quotes and quotes for your customers."}
        actions={<>
          <ButtonLink href="/quotes/settings" variant="secondary">Settings</ButtonLink>
          {canWriteQuotes(me) && <ButtonLink href="/quotes/new">New quote</ButtonLink>}
        </>}
      />
      {linked && (
        <p className="mb-4 text-sm text-slate-700">
          Showing quotes for {LINK_FILTERS[linked[0]]}, including earlier revisions.{" "}
          <Link href="/quotes" className="font-medium text-brand-700 hover:underline">Show all quotes</Link>
        </p>
      )}
      <Card>
        <form role="search" aria-label="Filter quotes" className="grid gap-4 px-5 py-4 sm:grid-cols-[2fr_1fr_auto]">
          <div>
            <label htmlFor="quote-q" className="text-sm font-medium text-slate-700">Search</label>
            <input id="quote-q" name="q" type="search" defaultValue={q} maxLength={100} placeholder="Title or number (QT-0007)" className={field} />
          </div>
          <div>
            <label htmlFor="quote-status" className="text-sm font-medium text-slate-700">Status</label>
            <select id="quote-status" name="status" defaultValue={status} className={field}>
              <option value="">All current</option>
              {QUOTE_STATUSES.map((s) => <option key={s} value={s}>{QUOTE_STATUS_LABELS[s]}</option>)}
            </select>
          </div>
          <div className="flex items-end gap-2">
            {linked && <input type="hidden" name={linked[0]} value={linked[1]} />}
            <button type="submit" className={buttonClass("primary")}>Apply</button>
            {(q || status) && <Link href="/quotes" className={buttonClass("secondary")}>Clear</Link>}
          </div>
        </form>
        <div className="border-t border-slate-200">
          {data.items.length === 0 ? (
            <EmptyState title="No quotes yet" description="Create a quote from a deal or an account." />
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200 text-sm">
                <caption className="sr-only">Quotes, page {pageNumber}</caption>
                <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-600">
                  <tr>
                    <th scope="col" className="px-5 py-3">Quote</th>
                    <th scope="col" className="px-5 py-3">Account</th>
                    <th scope="col" className="px-5 py-3">Status</th>
                    <th scope="col" className="px-5 py-3 text-right">Total</th>
                    <th scope="col" className="hidden px-5 py-3 md:table-cell">Valid until</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {data.items.map((x) => (
                    <tr key={x.id}>
                      <th scope="row" className="px-5 py-3 text-left font-medium">
                        <Link href={`/quotes/${x.id}`} className="text-brand-700 hover:underline">
                          <span className="font-mono text-xs text-slate-500">{quoteNumber(x.number, x.revision)}</span> {x.title}
                        </Link>
                      </th>
                      <td className="px-5 py-3 text-slate-700">{accountName(x.account_id)}</td>
                      <td className="px-5 py-3">
                        <span className={cx("rounded-full px-2.5 py-0.5 text-xs font-medium", QUOTE_STATUS_STYLE[x.status])}>{QUOTE_STATUS_LABELS[x.status]}</span>
                        {x.expired && <span className="ml-2 rounded-full bg-red-50 px-2 py-0.5 text-xs text-red-700">Expired</span>}
                      </td>
                      <td className="px-5 py-3 text-right whitespace-nowrap">{formatAmounts([{ currency: x.currency, amount: x.total }])}</td>
                      <td className="hidden px-5 py-3 text-slate-700 md:table-cell">{formatDate(x.valid_until)}</td>
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
