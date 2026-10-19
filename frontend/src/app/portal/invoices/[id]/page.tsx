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
import { ButtonLink, Card } from "@/components/ui";
import { ApiError } from "@/lib/api-error";
import type { PortalAccount, PortalInvoice } from "@/lib/api-types";
import { formatDate } from "@/lib/format";
import { apiFetch } from "@/lib/server/api";

export const metadata: Metadata = { title: "Invoice" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * One of the customer's invoices. Another customer's invoice, a draft, or an invoice in
 * another tenant is answered by the API with 404, exactly like one that doesn't exist.
 */
export default async function PortalInvoicePage({
  params,
}: PageProps<"/portal/invoices/[id]">) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  let invoice: PortalInvoice;
  try {
    invoice = await apiFetch<PortalInvoice>(`/portal/invoices/${id}`);
  } catch (error) {
    if (
      error instanceof ApiError &&
      (error.status === 404 || error.status === 403)
    )
      notFound();
    throw error;
  }
  const account = await apiFetch<PortalAccount>(
    `/portal/accounts/${invoice.account_id}`,
  ).catch(() => null);
  const money = (v: string) => formatMoney(v, invoice.currency);
  const owed = invoice.balance_due !== "0.00";

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link href="/portal/invoices" className="font-medium text-brand-700 hover:underline">← Invoices</Link>
      </nav>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="font-mono text-2xl font-semibold tracking-tight text-slate-900">{invoiceNumber(invoice.number)}</h1>
          <PaymentStateBadge state={invoice.payment_state} portal />
        </div>
        <ButtonLink href={`/portal/tickets/new?account=${invoice.account_id}`} variant="secondary">Question about this invoice?</ButtonLink>
      </div>

      {owed && (
        <div role="note" className={invoice.payment_state === "overdue" ? "mb-6 rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-900" : "mb-6 rounded-md border border-sky-200 bg-sky-50 p-4 text-sm text-sky-900"}>
          <p className="font-medium">
            {money(invoice.balance_due)} {invoice.payment_state === "overdue" ? "was due" : "is due"} on {formatDate(invoice.due_date)}.
          </p>
          <p className="mt-1">Please quote {invoiceNumber(invoice.number)} with your payment. Payments can take a few days to appear here.</p>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">Invoice lines</h2>
            <OrderLinesTable lines={invoice.lines} currency={invoice.currency} subtotal={invoice.subtotal} taxTotal={invoice.tax_total} total={invoice.total} />
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
          <Card>
            <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">Payments received</h2>
            {invoice.payments.length === 0 ? (
              <p className="px-5 py-6 text-sm text-slate-600">No payments received yet.</p>
            ) : (
              <ul className="divide-y divide-slate-100">
                {invoice.payments.map((p, i) => (
                  <li key={i} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 text-sm">
                    <span>{formatDate(p.received_on)} · {PAYMENT_METHOD_LABELS[p.method]}{p.reference ? ` · ${p.reference}` : ""}</span>
                    <span className="tabular-nums">{money(p.amount)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
        <div className="space-y-6">
          <Card>
            <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">Balance</h2>
            <BalanceSummary currency={invoice.currency} total={invoice.total} credited={invoice.amount_credited} paid={invoice.amount_paid} balance={invoice.balance_due} />
          </Card>
          <Card>
            <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">Details</h2>
            <dl className="space-y-3 px-5 py-4 text-sm">
              {([
                ["Account", account ? <Link href={`/portal/accounts/${account.id}`} className="text-brand-700 hover:underline">{account.name}</Link> : "Your account"],
                ["Order", <Link key="o" href={`/portal/orders/${invoice.order_id}`} className="text-brand-700 hover:underline">View order</Link>],
                ["Your reference", invoice.customer_reference ?? "—"],
                ["Issued", formatDate(invoice.issue_date)],
                ["Due", formatDate(invoice.due_date)],
              ] as [string, React.ReactNode][]).map(([label, value]) => (
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
