import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import {
  ORDER_STATUS_LABELS,
  OrderLinesTable,
  OrderStatusBadge,
  orderNumber,
} from "@/components/orders";
import { PaymentStateBadge, invoiceNumber } from "@/components/invoices";
import { Card, Forbidden, SuccessAlert } from "@/components/ui";
import { ApiError } from "@/lib/api-error";
import type {
  Account,
  DirectoryUser,
  InvoicePage,
  Order,
  QuotePage,
} from "@/lib/api-types";
import { formatDate, formatDateTime } from "@/lib/format";
import { orderActionsFor } from "@/lib/order-rules";
import {
  canManageInvoices,
  canReadAccounts,
  canReadInvoices,
  canReadQuotes,
  canWriteOrders,
} from "@/lib/permissions";
import { quoteNumber } from "@/lib/quotes";
import { apiFetch, getMe } from "@/lib/server/api";

import { createInvoiceFromOrder } from "../../invoices/actions";
import { CreateInvoiceButton } from "../../invoices/create-invoice-button";
import { changeOrderStatus } from "../actions";
import { OrderActionBar } from "./order-action-bar";

export const metadata: Metadata = { title: "Order" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const DONE: Record<string, string> = {
  created: "The draft order was saved.",
  updated: "The draft order was updated.",
  confirmed:
    "The order was confirmed. The customer can now see it in their portal.",
  in_fulfilment: "Fulfilment has started.",
  shipped: "The order was marked as shipped.",
  delivered: "The order was marked as delivered.",
  cancelled: "The order was cancelled.",
};

async function loadOrder(id: string): Promise<Order | "forbidden"> {
  if (!UUID.test(id)) notFound();
  try {
    return await apiFetch<Order>(`/orders/${id}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    if (error instanceof ApiError && error.status === 403) return "forbidden";
    throw error;
  }
}

export default async function OrderPage({
  params,
  searchParams,
}: PageProps<"/orders/[id]">) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  const [order, me] = await Promise.all([loadOrder(id), getMe()]);
  if (order === "forbidden") return <Forbidden />;

  const [account, people, invoices, source] = await Promise.all([
    canReadAccounts(me)
      ? apiFetch<Account>(`/accounts/${order.account_id}`).catch(() => null)
      : Promise.resolve(null),
    apiFetch<DirectoryUser[]>("/users").catch(() => []),
    canReadInvoices(me)
      ? apiFetch<InvoicePage>(`/invoices?order_id=${order.id}&limit=20`)
          .then((p) => p.items)
          .catch(() => null)
      : Promise.resolve(null),
    // The quote this order was created from (if any) - at most one.
    canReadQuotes(me)
      ? apiFetch<QuotePage>(
          `/quotes?order_id=${order.id}&include_superseded=true&limit=1`,
        )
          .then((p) => p.items[0] ?? null)
          .catch(() => null)
      : Promise.resolve(null),
  ]);
  const liveInvoice = invoices?.find((i) => i.status !== "discarded");
  const invoiceable =
    !liveInvoice &&
    canManageInvoices(me) &&
    !["draft", "cancelled"].includes(order.status);
  const done = typeof query.done === "string" ? DONE[query.done] : undefined;
  const createdBy =
    people.find((p) => p.id === order.created_by_user_id)?.display_name ?? "—";
  const statusActions = Object.fromEntries(
    orderActionsFor(me, order.status).map((target) => [
      target,
      changeOrderStatus.bind(null, order.id, target),
    ]),
  );
  const editable = order.status === "draft" && canWriteOrders(me);

  const facts: [string, React.ReactNode][] = [
    [
      "Account",
      account ? (
        <Link
          href={`/accounts/${account.id}`}
          className="text-brand-700 hover:underline"
        >
          {account.name}
        </Link>
      ) : (
        "Customer account"
      ),
    ],
    ["Customer reference", order.customer_reference ?? "—"],
    [
      "Expected delivery",
      order.expected_delivery_date
        ? formatDate(order.expected_delivery_date)
        : "—",
    ],
    ["Tracking", order.tracking_reference ?? "—"],
    ["Created", `${formatDateTime(order.created_at)} by ${createdBy}`],
  ];
  if (order.confirmed_at)
    facts.push(["Confirmed", formatDateTime(order.confirmed_at)]);
  if (order.shipped_at)
    facts.push(["Shipped", formatDateTime(order.shipped_at)]);
  if (order.delivered_at)
    facts.push(["Delivered", formatDateTime(order.delivered_at)]);
  if (source)
    facts.push([
      "From quote",
      <Link
        key="quote"
        href={`/quotes/${source.id}`}
        className="text-brand-700 hover:underline"
      >
        {quoteNumber(source.number, source.revision)}
      </Link>,
    ]);

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link href="/orders" className="font-medium text-brand-700 hover:underline">← Orders</Link>
      </nav>
      {done && <div className="mb-4"><SuccessAlert>{done}</SuccessAlert></div>}

      <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="font-mono text-2xl font-semibold tracking-tight text-slate-900">{orderNumber(order.number)}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <OrderStatusBadge status={order.status} />
            {order.status === "draft" && <span className="text-sm text-slate-600">Not visible to the customer yet.</span>}
          </div>
        </div>
        <OrderActionBar
          key={order.version}
          order={{ number: order.number, version: order.version, expectedDelivery: order.expected_delivery_date }}
          editHref={editable ? `/orders/${order.id}/edit` : undefined}
          actions={statusActions}
          invoiced={Boolean(liveInvoice)}
        />
      </div>

      {order.status === "cancelled" && (
        <div role="note" className="mb-6 rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-900">
          <p className="font-medium">Cancelled {order.cancelled_at && formatDateTime(order.cancelled_at)}</p>
          <p className="mt-1">Reason shown to the customer: {order.cancellation_reason}</p>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">Lines</h2>
            <OrderLinesTable lines={order.lines} currency={order.currency} subtotal={order.subtotal} taxTotal={order.tax_total} total={order.total} />
          </Card>
          <Card>
            <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">History</h2>
            <ol className="space-y-3 px-5 py-4 text-sm">
              {order.events.map((e, i) => (
                <li key={i} className="flex flex-wrap gap-x-2">
                  <span className="font-medium text-slate-900">{ORDER_STATUS_LABELS[e.to_status]}</span>
                  <span className="text-slate-600">by {e.actor_name} · <time dateTime={e.created_at}>{formatDateTime(e.created_at)}</time></span>
                  {e.note && <p className="w-full text-slate-700">Note: {e.note}</p>}
                </li>
              ))}
            </ol>
          </Card>
        </div>
        <div className="space-y-6">
          {invoices && (
            <Card>
              <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-5 py-4">
                <h2 className="text-base font-semibold text-slate-900">Invoice</h2>
                {invoiceable && <CreateInvoiceButton action={createInvoiceFromOrder.bind(null, order.id)} />}
              </div>
              {liveInvoice ? (
                <p className="flex items-center justify-between gap-3 px-5 py-4 text-sm">
                  <Link href={`/invoices/${liveInvoice.id}`} className="font-mono font-medium text-brand-700 hover:underline">{invoiceNumber(liveInvoice.number)}</Link>
                  <PaymentStateBadge state={liveInvoice.payment_state} />
                </p>
              ) : (
                <p className="px-5 py-4 text-sm text-slate-600">
                  {["draft", "cancelled"].includes(order.status) ? "Only confirmed orders can be invoiced." : "Not invoiced yet."}
                </p>
              )}
            </Card>
          )}
          <Card>
            <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">Details</h2>
            <dl className="space-y-3 px-5 py-4 text-sm">
              {facts.map(([label, value]) => (
                <div key={label}>
                  <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</dt>
                  <dd className="mt-0.5 text-slate-900">{value}</dd>
                </div>
              ))}
            </dl>
          </Card>
          {order.internal_note && (
            <Card className="bg-amber-50 ring-amber-200">
              <h2 className="px-5 pt-4 text-sm font-semibold text-amber-900">Internal note — not visible to the customer</h2>
              <p className="whitespace-pre-line px-5 pb-4 pt-1 text-sm text-amber-950">{order.internal_note}</p>
            </Card>
          )}
        </div>
      </div>
    </>
  ); // prettier-ignore
}
