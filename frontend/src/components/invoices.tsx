import Link from "next/link";

import { formatMoney } from "@/components/orders";
import { cx } from "@/components/ui";
import type {
  PaymentMethod,
  PaymentState,
  PortalInvoiceSummary,
} from "@/lib/api-types";
import { formatDate } from "@/lib/format";

/** Shared invoice UI (staff and portal): numbers, state badges, the balance summary. */

export const invoiceNumber = (n: number | null) =>
  n === null ? "Draft invoice" : `INV-${String(n).padStart(4, "0")}`;
export const creditNoteNumber = (n: number) =>
  `CN-${String(n).padStart(4, "0")}`;

export const PAYMENT_STATE_LABELS: Record<PaymentState, string> = {
  draft: "Draft",
  discarded: "Discarded",
  open: "Open",
  partially_paid: "Partially paid",
  overdue: "Overdue",
  paid: "Paid",
  credited: "Credited",
};

/** What customers read. They never see drafts or discarded invoices. */
export const PORTAL_PAYMENT_STATE_LABELS: Record<PaymentState, string> = {
  ...PAYMENT_STATE_LABELS,
  open: "Awaiting payment",
  partially_paid: "Partly paid",
  overdue: "Payment overdue",
};

export const PAYMENT_METHOD_LABELS: Record<PaymentMethod, string> = {
  bank_transfer: "Bank transfer",
  card: "Card",
  cash: "Cash",
  other: "Other",
};

const pill =
  "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset";
const stateStyle: Record<PaymentState, string> = {
  draft: "bg-slate-100 text-slate-700 ring-slate-300",
  discarded: "bg-slate-50 text-slate-500 ring-slate-200 line-through",
  open: "bg-sky-50 text-sky-800 ring-sky-200",
  partially_paid: "bg-amber-50 text-amber-800 ring-amber-200",
  overdue: "bg-red-600 text-white ring-red-600",
  paid: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  credited: "bg-violet-50 text-violet-800 ring-violet-200",
};

export function PaymentStateBadge({
  state,
  portal = false,
}: {
  state: PaymentState;
  portal?: boolean;
}) {
  return (
    <span className={cx(pill, stateStyle[state])}>
      {(portal ? PORTAL_PAYMENT_STATE_LABELS : PAYMENT_STATE_LABELS)[state]}
    </span>
  );
}

/** Total, credit notes, payments and what is still owed - the numbers people ask about. */
export function BalanceSummary({
  currency,
  total,
  credited,
  paid,
  balance,
}: {
  currency: string;
  total: string;
  credited: string;
  paid: string;
  balance: string;
}) {
  const money = (v: string) => formatMoney(v, currency);
  return (
    <dl aria-label="Balance" className="space-y-2 px-5 py-4 text-sm">
      <div className="flex justify-between gap-6"><dt className="text-slate-600">Invoice total</dt><dd className="tabular-nums">{money(total)}</dd></div>
      <div className="flex justify-between gap-6"><dt className="text-slate-600">Credit notes</dt><dd className="tabular-nums">− {money(credited)}</dd></div>
      <div className="flex justify-between gap-6"><dt className="text-slate-600">Payments received</dt><dd className="tabular-nums">− {money(paid)}</dd></div>
      <div className="flex justify-between gap-6 border-t border-slate-200 pt-2 text-base font-semibold text-slate-900">
        <dt>Amount due</dt><dd className="tabular-nums">{money(balance)}</dd>
      </div>
    </dl>
  ); // prettier-ignore
}

/** The customer's list of invoices (portal home, account page, invoices page). */
export function PortalInvoiceList({
  invoices,
  emptyText,
}: {
  invoices: PortalInvoiceSummary[];
  emptyText: string;
}) {
  if (invoices.length === 0)
    return <p className="px-5 py-6 text-sm text-slate-600">{emptyText}</p>;
  return (
    <ul className="divide-y divide-slate-100">
      {invoices.map((i) => (
        <li key={i.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
          <div className="min-w-0">
            <Link href={`/portal/invoices/${i.id}`} className="text-sm font-medium text-brand-700 hover:underline">
              <span className="font-mono">{invoiceNumber(i.number)}</span>
            </Link>
            <p className="text-xs text-slate-500">
              {formatMoney(i.total, i.currency)} · issued {formatDate(i.issue_date)}
              {i.balance_due !== "0.00" && <> · <span className="font-medium text-slate-700">{formatMoney(i.balance_due, i.currency)} due {formatDate(i.due_date)}</span></>}
            </p>
          </div>
          <PaymentStateBadge state={i.payment_state} portal />
        </li>
      ))}
    </ul>
  ); // prettier-ignore
}
