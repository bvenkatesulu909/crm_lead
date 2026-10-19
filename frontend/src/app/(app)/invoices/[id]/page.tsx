import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import {
  BalanceSummary,
  PAYMENT_METHOD_LABELS,
  PaymentStateBadge,
  creditNoteNumber,
  invoiceNumber,
} from "@/components/invoices";
import { OrderLinesTable, formatMoney } from "@/components/orders";
import { Card, Forbidden, SuccessAlert, cx } from "@/components/ui";
import { ApiError } from "@/lib/api-error";
import type { Account, Invoice, Order } from "@/lib/api-types";
import { formatDate, formatDateTime } from "@/lib/format";
import {
  canManageInvoices,
  canReadAccounts,
  canReadOrders,
  canRecordPayments,
} from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import {
  discardInvoice,
  issueCreditNote,
  issueInvoice,
  recordPayment,
  reversePayment,
} from "../actions";
import { InvoiceActionBar, ReversePaymentButton } from "./invoice-action-bar";

export const metadata: Metadata = { title: "Invoice" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const DONE: Record<string, string> = {
  created: "The draft invoice was created from the order.",
  issued:
    "The invoice was issued. The customer can now see it in their portal.",
  discarded: "The draft was discarded.",
  paid: "The payment was recorded.",
  reversed: "The payment was reversed.",
  credited: "The credit note was issued.",
};

async function loadInvoice(id: string): Promise<Invoice | "forbidden"> {
  if (!UUID.test(id)) notFound();
  try {
    return await apiFetch<Invoice>(`/invoices/${id}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    if (error instanceof ApiError && error.status === 403) return "forbidden";
    throw error;
  }
}

const isoDay = (d: Date) => d.toISOString().slice(0, 10);

export default async function InvoicePage({
  params,
  searchParams,
}: PageProps<"/invoices/[id]">) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  const [invoice, me] = await Promise.all([loadInvoice(id), getMe()]);
  if (invoice === "forbidden") return <Forbidden />;

  const [account, order] = await Promise.all([
    canReadAccounts(me)
      ? apiFetch<Account>(`/accounts/${invoice.account_id}`).catch(() => null)
      : Promise.resolve(null),
    canReadOrders(me)
      ? apiFetch<Order>(`/orders/${invoice.order_id}`).catch(() => null)
      : Promise.resolve(null),
  ]);
  const done = typeof query.done === "string" ? DONE[query.done] : undefined;
  const money = (v: string) => formatMoney(v, invoice.currency);
  const now = new Date();
  const today = isoDay(now);
  const in14 = isoDay(new Date(now.getTime() + 14 * 86_400_000));
  const draft = invoice.status === "draft";
  const owed = invoice.status === "issued" && invoice.balance_due !== "0.00";
  const cashier = canRecordPayments(me) && invoice.status === "issued";

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
    [
      "Order",
      order ? (
        <Link
          href={`/orders/${order.id}`}
          className="font-mono text-brand-700 hover:underline"
        >
          SO-{String(order.number).padStart(4, "0")}
        </Link>
      ) : (
        "—"
      ),
    ],
    ["Customer reference", invoice.customer_reference ?? "—"],
    ["Issued", invoice.issue_date ? formatDate(invoice.issue_date) : "Not yet"],
    [
      "Due",
      invoice.due_date ? formatDate(invoice.due_date) : "Set when issuing",
    ],
  ];

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link href="/invoices" className="font-medium text-brand-700 hover:underline">← Invoices</Link>
      </nav>
      {done && <div className="mb-4"><SuccessAlert>{done}</SuccessAlert></div>}

      <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="font-mono text-2xl font-semibold tracking-tight text-slate-900">{invoiceNumber(invoice.number)}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <PaymentStateBadge state={invoice.payment_state} />
            {draft && <span className="text-sm text-slate-600">No number yet and not visible to the customer.</span>}
          </div>
        </div>
        <InvoiceActionBar
          key={invoice.version}
          invoice={{ number: invoice.number, version: invoice.version, currency: invoice.currency, balance: invoice.balance_due }}
          today={today}
          defaultDueDate={in14}
          actions={{
            issue: draft && canManageInvoices(me) ? issueInvoice.bind(null, invoice.id) : undefined,
            discard: draft && canManageInvoices(me) ? discardInvoice.bind(null, invoice.id) : undefined,
            pay: owed && canRecordPayments(me) ? recordPayment.bind(null, invoice.id) : undefined,
            credit: owed && canManageInvoices(me) ? issueCreditNote.bind(null, invoice.id) : undefined,
          }}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">Lines</h2>
            <OrderLinesTable lines={invoice.lines} currency={invoice.currency} subtotal={invoice.subtotal} taxTotal={invoice.tax_total} total={invoice.total} />
          </Card>
          <Card>
            <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">Payments</h2>
            {invoice.payments.length === 0 ? (
              <p className="px-5 py-6 text-sm text-slate-600">No payments recorded.</p>
            ) : (
              <ul className="divide-y divide-slate-100">
                {invoice.payments.map((p) => {
                  const reversal = p.reverses_payment_id !== null;
                  return (
                    <li key={p.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 text-sm">
                      <div>
                        <p className={cx("font-medium tabular-nums", (reversal || p.reversed) && "text-slate-500", p.reversed && "line-through")}>
                          {reversal ? `Reversal − ${money(p.amount)}` : money(p.amount)}
                        </p>
                        <p className="text-xs text-slate-500">
                          {reversal ? `Reason: ${p.reversal_reason}` : `${PAYMENT_METHOD_LABELS[p.method]} · received ${formatDate(p.received_on)}${p.reference ? ` · ${p.reference}` : ""}`}
                          {" "}· recorded by {p.recorded_by_name}, {formatDateTime(p.created_at)}
                        </p>
                      </div>
                      {cashier && !reversal && !p.reversed && (
                        <ReversePaymentButton amount={money(p.amount)} action={reversePayment.bind(null, invoice.id, p.id)} />
                      )}
                      {p.reversed && <span className="text-xs font-medium text-slate-500">Reversed</span>}
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>
          {invoice.credit_notes.length > 0 && (
            <Card>
              <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">Credit notes</h2>
              <ul className="divide-y divide-slate-100">
                {invoice.credit_notes.map((n) => (
                  <li key={n.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 text-sm">
                    <div>
                      <p className="font-mono font-medium">{creditNoteNumber(n.number)}</p>
                      <p className="text-xs text-slate-500">{formatDate(n.issue_date)} · {n.reason}</p>
                    </div>
                    <span className="tabular-nums">− {money(n.total)}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
        <div className="space-y-6">
          <Card>
            <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">Balance</h2>
            <BalanceSummary currency={invoice.currency} total={invoice.total} credited={invoice.amount_credited} paid={invoice.amount_paid} balance={invoice.balance_due} />
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
      </div>
    </>
  ); // prettier-ignore
}
