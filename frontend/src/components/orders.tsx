import Link from "next/link";

import { cx } from "@/components/ui";
import type {
  OrderLine,
  OrderStatus,
  PortalOrder,
  PortalOrderSummary,
} from "@/lib/api-types";
import { formatDate, formatDateTime } from "@/lib/format";

/** Shared order UI (staff and portal): numbers, money, status badges, the lines table. */

export const orderNumber = (n: number) => `SO-${String(n).padStart(4, "0")}`;

export const ORDER_STATUS_LABELS: Record<OrderStatus, string> = {
  draft: "Draft",
  confirmed: "Confirmed",
  in_fulfilment: "In fulfilment",
  shipped: "Shipped",
  delivered: "Delivered",
  cancelled: "Cancelled",
};

/** What customers read. They never see drafts. */
export const PORTAL_ORDER_STATUS_LABELS: Record<OrderStatus, string> = {
  ...ORDER_STATUS_LABELS,
  confirmed: "Order received",
  in_fulfilment: "Being prepared",
  shipped: "On its way",
};

const pill =
  "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset";
const statusStyle: Record<OrderStatus, string> = {
  draft: "bg-slate-100 text-slate-700 ring-slate-300",
  confirmed: "bg-sky-50 text-sky-800 ring-sky-200",
  in_fulfilment: "bg-amber-50 text-amber-800 ring-amber-200",
  shipped: "bg-violet-50 text-violet-800 ring-violet-200",
  delivered: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  cancelled: "bg-red-50 text-red-800 ring-red-200",
};

export function OrderStatusBadge({
  status,
  portal = false,
}: {
  status: OrderStatus;
  portal?: boolean;
}) {
  return (
    <span className={cx(pill, statusStyle[status])}>
      {(portal ? PORTAL_ORDER_STATUS_LABELS : ORDER_STATUS_LABELS)[status]}
    </span>
  );
}

/**
 * "1234.5" + "EUR" -> "€1,234.50". The API sends decimal strings; Intl formats the string
 * itself, so no float rounding happens on the way.
 */
export function formatMoney(amount: string, currency: string): string {
  const format = new Intl.NumberFormat("en-GB", {
    style: "currency",
    currency,
  });
  // Intl.NumberFormat accepts decimal strings exactly (ES2023); TS types still say number.
  return format.format(amount as unknown as number);
}

/** "1.500" -> "1.5", "3.000" -> "3" */
export function formatQuantity(quantity: string): string {
  return quantity.includes(".")
    ? quantity.replace(/0+$/, "").replace(/\.$/, "")
    : quantity;
}

export function OrderLinesTable({
  lines,
  currency,
  subtotal,
  taxTotal,
  total,
}: {
  lines: OrderLine[];
  currency: string;
  subtotal: string;
  taxTotal: string;
  total: string;
}) {
  const money = (v: string) => formatMoney(v, currency);
  if (lines.length === 0)
    return <p className="px-5 py-6 text-sm text-slate-600">No lines yet.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <caption className="sr-only">Order lines</caption>
        <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-600">
          <tr>
            <th scope="col" className="px-5 py-3">Item</th>
            <th scope="col" className="px-5 py-3 text-right">Qty</th>
            <th scope="col" className="hidden px-5 py-3 text-right sm:table-cell">Unit price</th>
            <th scope="col" className="hidden px-5 py-3 text-right md:table-cell">Tax</th>
            <th scope="col" className="px-5 py-3 text-right">Amount</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 bg-white">
          {lines.map((line) => (
            <tr key={line.position}>
              <th scope="row" className="px-5 py-3 text-left font-normal text-slate-900">
                {line.description}
                {line.product_code && <span className="ml-2 font-mono text-xs text-slate-500">{line.product_code}</span>}
              </th>
              <td className="px-5 py-3 text-right tabular-nums">{formatQuantity(line.quantity)}</td>
              <td className="hidden px-5 py-3 text-right tabular-nums sm:table-cell">{money(line.unit_price)}</td>
              <td className="hidden px-5 py-3 text-right tabular-nums text-slate-600 md:table-cell">
                {formatQuantity(line.tax_rate)} % · {money(line.line_tax)}
              </td>
              <td className="px-5 py-3 text-right tabular-nums">{money(line.line_total)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <dl className="ml-auto max-w-xs space-y-1 border-t border-slate-200 px-5 py-4 text-sm">
        <div className="flex justify-between gap-6"><dt className="text-slate-600">Subtotal</dt><dd className="tabular-nums">{money(subtotal)}</dd></div>
        <div className="flex justify-between gap-6"><dt className="text-slate-600">Tax</dt><dd className="tabular-nums">{money(taxTotal)}</dd></div>
        <div className="flex justify-between gap-6 font-semibold text-slate-900"><dt>Total</dt><dd className="tabular-nums">{money(total)}</dd></div>
      </dl>
    </div>
  ); // prettier-ignore
}

/** The customer's list of orders (portal home, account page and the orders page). */
export function PortalOrderList({
  orders,
  emptyText,
}: {
  orders: PortalOrderSummary[];
  emptyText: string;
}) {
  if (orders.length === 0)
    return <p className="px-5 py-6 text-sm text-slate-600">{emptyText}</p>;
  return (
    <ul className="divide-y divide-slate-100">
      {orders.map((o) => (
        <li key={o.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
          <div className="min-w-0">
            <Link href={`/portal/orders/${o.id}`} className="text-sm font-medium text-brand-700 hover:underline">
              <span className="font-mono">{orderNumber(o.number)}</span>
              {o.customer_reference && <span className="ml-2 font-normal text-slate-600">Your ref. {o.customer_reference}</span>}
            </Link>
            <p className="text-xs text-slate-500">
              {formatMoney(o.total, o.currency)}
              {o.expected_delivery_date && o.status !== "delivered" && o.status !== "cancelled" && <> · expected {formatDate(o.expected_delivery_date)}</>}
            </p>
          </div>
          <OrderStatusBadge status={o.status} portal />
        </li>
      ))}
    </ul>
  ); // prettier-ignore
}

const STEPS: OrderStatus[] = [
  "confirmed",
  "in_fulfilment",
  "shipped",
  "delivered",
];

/** Where the order is: received → being prepared → on its way → delivered. */
export function OrderProgress({
  order,
}: {
  order: Pick<PortalOrder, "status" | "timeline">;
}) {
  if (order.status === "cancelled" || order.status === "draft") return null;
  const reached = STEPS.indexOf(order.status);
  const when = (status: OrderStatus) =>
    order.timeline.find((t) => t.status === status)?.at;
  return (
    <ol aria-label="Order progress" className="grid gap-3 sm:grid-cols-4">
      {STEPS.map((step, i) => {
        const done = i <= reached;
        const at = when(step);
        return (
          <li key={step} aria-current={i === reached ? "step" : undefined}
            className={cx("rounded-lg p-4 ring-1", done ? "bg-brand-50 ring-brand-200" : "bg-white ring-slate-200")}>
            <p className={cx("text-sm font-semibold", done ? "text-brand-800" : "text-slate-500")}>
              {done ? "✓ " : ""}{PORTAL_ORDER_STATUS_LABELS[step]}
            </p>
            <p className="mt-1 text-xs text-slate-600">
              {at ? <time dateTime={at}>{formatDateTime(at)}</time> : done ? "" : "Not yet"}
            </p>
          </li>
        );
      })}
    </ol>
  ); // prettier-ignore
}
