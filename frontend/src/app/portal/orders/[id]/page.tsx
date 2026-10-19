import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { invoiceNumber } from "@/components/invoices";
import {
  OrderLinesTable,
  OrderProgress,
  OrderStatusBadge,
  orderNumber,
} from "@/components/orders";
import { ButtonLink, Card } from "@/components/ui";
import { ApiError } from "@/lib/api-error";
import type {
  PortalAccount,
  PortalInvoiceSummary,
  PortalOrder,
} from "@/lib/api-types";
import { formatDate, formatDateTime } from "@/lib/format";
import { apiFetch } from "@/lib/server/api";

export const metadata: Metadata = { title: "Order" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * One of the customer's orders. Another customer's order, a draft, or an order in another
 * tenant is answered by the API with 404, exactly like an order that doesn't exist.
 */
export default async function PortalOrderPage({
  params,
}: PageProps<"/portal/orders/[id]">) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  let order: PortalOrder;
  try {
    order = await apiFetch<PortalOrder>(`/portal/orders/${id}`);
  } catch (error) {
    if (
      error instanceof ApiError &&
      (error.status === 404 || error.status === 403)
    )
      notFound();
    throw error;
  }
  const [account, invoices] = await Promise.all([
    apiFetch<PortalAccount>(`/portal/accounts/${order.account_id}`).catch(
      () => null,
    ),
    apiFetch<PortalInvoiceSummary[]>(
      `/portal/invoices?order_id=${order.id}&limit=5`,
    ).catch(() => []),
  ]);
  const active = order.status !== "delivered" && order.status !== "cancelled";

  const facts: [string, React.ReactNode][] = [
    [
      "Account",
      account ? (
        <Link
          href={`/portal/accounts/${account.id}`}
          className="text-brand-700 hover:underline"
        >
          {account.name}
        </Link>
      ) : (
        "Your account"
      ),
    ],
    ["Your reference", order.customer_reference ?? "—"],
    ["Ordered", order.confirmed_at ? formatDateTime(order.confirmed_at) : "—"],
  ];
  if (active && order.expected_delivery_date)
    facts.push(["Expected delivery", formatDate(order.expected_delivery_date)]);
  if (order.tracking_reference)
    facts.push(["Tracking reference", order.tracking_reference]);
  if (order.delivered_at)
    facts.push(["Delivered", formatDateTime(order.delivered_at)]);
  for (const invoice of invoices)
    facts.push([
      "Invoice",
      <Link
        key={invoice.id}
        href={`/portal/invoices/${invoice.id}`}
        className="font-mono text-brand-700 hover:underline"
      >
        {invoiceNumber(invoice.number)}
      </Link>,
    ]);

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link href="/portal/orders" className="font-medium text-brand-700 hover:underline">← Orders</Link>
      </nav>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="font-mono text-2xl font-semibold tracking-tight text-slate-900">{orderNumber(order.number)}</h1>
          <OrderStatusBadge status={order.status} portal />
        </div>
        <ButtonLink href={`/portal/tickets/new?account=${order.account_id}`} variant="secondary">Question about this order?</ButtonLink>
      </div>

      {order.status === "cancelled" ? (
        <div role="note" className="mb-6 rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-900">
          <p className="font-medium">This order was cancelled{order.cancelled_at && ` on ${formatDate(order.cancelled_at)}`}.</p>
          {order.cancellation_reason && <p className="mt-1">Reason: {order.cancellation_reason}</p>}
        </div>
      ) : (
        <div className="mb-6"><OrderProgress order={order} /></div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">What you ordered</h2>
          <OrderLinesTable lines={order.lines} currency={order.currency} subtotal={order.subtotal} taxTotal={order.tax_total} total={order.total} />
        </Card>
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
      </div>
    </>
  ); // prettier-ignore
}
