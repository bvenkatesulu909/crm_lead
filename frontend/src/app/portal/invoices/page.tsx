import type { Metadata } from "next";
import Link from "next/link";

import { PortalInvoiceList } from "@/components/invoices";
import { formatMoney } from "@/components/orders";
import { Card, ErrorAlert } from "@/components/ui";
import { toErrorInfo } from "@/lib/api-error";
import type { PortalInvoiceSummary } from "@/lib/api-types";
import { centsToDecimal, toScaled } from "@/lib/order-math";
import { apiFetch } from "@/lib/server/api";

export const metadata: Metadata = { title: "Invoices" };

export default async function PortalInvoicesPage() {
  let invoices: PortalInvoiceSummary[];
  try {
    // The API returns only issued invoices of this customer's own accounts.
    invoices = await apiFetch<PortalInvoiceSummary[]>(
      "/portal/invoices?limit=100",
    );
  } catch (error) {
    return (
      <ErrorAlert
        title="Your invoices could not be loaded"
        error={toErrorInfo(error)}
      />
    );
  }
  // Amount owed per currency (an account could be billed in more than one currency).
  // Exact cents (BigInt), never float arithmetic on money.
  const owed = new Map<string, bigint>();
  for (const i of invoices) {
    const cents = toScaled(i.balance_due, 2);
    if (cents)
      owed.set(i.currency, (owed.get(i.currency) ?? BigInt(0)) + cents);
  }

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link href="/portal" className="font-medium text-brand-700 hover:underline">
          ← Portal home
        </Link>
      </nav>
      <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Invoices</h1>
      <p className="mt-1 mb-6 text-sm text-slate-600">
        {owed.size === 0
          ? "Nothing is currently owed."
          : `Currently owed: ${[...owed].map(([currency, cents]) => formatMoney(centsToDecimal(cents), currency)).join(" + ")}.`}
      </p>
      <Card>
        <PortalInvoiceList invoices={invoices} emptyText="No invoices yet." />
      </Card>
    </>
  ); // prettier-ignore
}
