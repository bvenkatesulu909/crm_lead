import type { Metadata } from "next";
import Link from "next/link";

import {
  ORDER_STATUS_LABELS,
  OrderStatusBadge,
  formatMoney,
  orderNumber,
} from "@/components/orders";
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
import {
  ORDER_STATUSES,
  type AccountPage,
  type OrderPage,
} from "@/lib/api-types";
import { formatDate } from "@/lib/format";
import { canReadAccounts, canWriteOrders, hasAny } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

export const metadata: Metadata = { title: "Orders" };

const PAGE_SIZE = 20;
const field =
  "mt-1 block w-full rounded-md border-0 bg-white px-3 py-2 text-sm text-slate-900 ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-brand-600";

type Raw = Record<string, string | string[] | undefined>;
const one = (v: string | string[] | undefined) =>
  (Array.isArray(v) ? v[0] : v) ?? "";

function parse(raw: Raw) {
  const status = one(raw.status);
  const page = Number.parseInt(one(raw.page), 10);
  return {
    q: one(raw.q).trim().slice(0, 100),
    status: (ORDER_STATUSES as readonly string[]).includes(status)
      ? status
      : "",
    page: Number.isFinite(page) && page > 0 && page <= 5000 ? page : 1,
  };
}
type Params = ReturnType<typeof parse>;

function href(p: Params, page: number) {
  const q = new URLSearchParams();
  if (p.q) q.set("q", p.q);
  if (p.status) q.set("status", p.status);
  if (page > 1) q.set("page", String(page));
  const s = q.toString();
  return s ? `/orders?${s}` : "/orders";
}

export default async function OrdersPage({
  searchParams,
}: PageProps<"/orders">) {
  const p = parse(await searchParams);
  const me = await getMe();
  const query = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String((p.page - 1) * PAGE_SIZE),
  });
  if (p.q) query.set("q", p.q);
  if (p.status) query.set("status", p.status);

  let data: OrderPage;
  let accounts: AccountPage["items"] = [];
  try {
    [data, accounts] = await Promise.all([
      apiFetch<OrderPage>(`/orders?${query}`),
      canReadAccounts(me)
        ? apiFetch<AccountPage>("/accounts?limit=200").then((a) => a.items)
        : Promise.resolve([]),
    ]);
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) return <Forbidden />;
    return (
      <>
        <PageHeader title="Orders" />
        <ErrorAlert
          title="Orders could not be loaded"
          error={toErrorInfo(error)}
        />
      </>
    );
  }
  const accountName = (id: string) =>
    accounts.find((a) => a.id === id)?.name ?? "Customer account";
  const filtered = Boolean(p.q || p.status);

  return (
    <>
      <PageHeader
        title="Orders"
        description={hasAny(me, "order:read:all") ? "All orders of your organisation." : "Orders of the customers you own."}
        actions={canWriteOrders(me) && <ButtonLink href="/orders/new">New order</ButtonLink>}
      />
      <Card>
        <form role="search" aria-label="Filter orders" className="grid gap-4 px-5 py-4 sm:grid-cols-[2fr_1fr_auto]">
          <div>
            <label htmlFor="o-q" className="text-sm font-medium text-slate-700">Search</label>
            <input id="o-q" name="q" type="search" defaultValue={p.q} maxLength={100} placeholder="SO-number or customer reference" className={field} />
          </div>
          <div>
            <label htmlFor="o-status" className="text-sm font-medium text-slate-700">Status</label>
            <select id="o-status" name="status" defaultValue={p.status} className={field}>
              <option value="">Any status</option>
              {ORDER_STATUSES.map((s) => <option key={s} value={s}>{ORDER_STATUS_LABELS[s]}</option>)}
            </select>
          </div>
          <div className="flex items-end gap-2">
            <button type="submit" className={buttonClass("primary")}>Apply</button>
            {filtered && <Link href="/orders" className={buttonClass("secondary")}>Clear</Link>}
          </div>
        </form>
        <div className="border-t border-slate-200">
          {data.items.length === 0 ? (
            <EmptyState
              title={filtered ? "No orders match your filters" : "No orders yet"}
              description={filtered ? "Try other filters." : "Orders you create for your customers appear here."}
              action={filtered ? <ButtonLink href="/orders" variant="secondary">Clear filters</ButtonLink> : canWriteOrders(me) && <ButtonLink href="/orders/new">Create an order</ButtonLink>}
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200 text-sm">
                <caption className="sr-only">Orders, page {p.page}</caption>
                <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-600">
                  <tr>
                    <th scope="col" className="px-5 py-3">Order</th>
                    <th scope="col" className="hidden px-5 py-3 md:table-cell">Account</th>
                    <th scope="col" className="px-5 py-3">Status</th>
                    <th scope="col" className="px-5 py-3 text-right">Total</th>
                    <th scope="col" className="hidden px-5 py-3 lg:table-cell">Expected delivery</th>
                    <th scope="col" className="hidden px-5 py-3 xl:table-cell">Created</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {data.items.map((o) => (
                    <tr key={o.id} className="hover:bg-slate-50">
                      <th scope="row" className="px-5 py-3 text-left font-medium">
                        <Link href={`/orders/${o.id}`} className="text-brand-700 hover:underline">
                          <span className="font-mono">{orderNumber(o.number)}</span>
                          {o.customer_reference && <span className="ml-2 text-xs font-normal text-slate-500">Ref. {o.customer_reference}</span>}
                        </Link>
                      </th>
                      <td className="hidden px-5 py-3 text-slate-700 md:table-cell">{accountName(o.account_id)}</td>
                      <td className="px-5 py-3"><OrderStatusBadge status={o.status} /></td>
                      <td className="whitespace-nowrap px-5 py-3 text-right tabular-nums">{formatMoney(o.total, o.currency)}</td>
                      <td className="hidden whitespace-nowrap px-5 py-3 text-slate-700 lg:table-cell">{o.expected_delivery_date ? formatDate(o.expected_delivery_date) : "—"}</td>
                      <td className="hidden whitespace-nowrap px-5 py-3 text-slate-700 xl:table-cell">{formatDate(o.created_at)}</td>
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
