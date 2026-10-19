import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { PrintButton } from "@/components/print-button";
import { QuoteLinesTable, QuoteTotals } from "@/components/quote-view";
import { ApiError } from "@/lib/api-error";
import type { PortalAccount, PortalQuote, Quote } from "@/lib/api-types";
import { formatDate } from "@/lib/format";
import { quoteNumber } from "@/lib/quotes";
import { apiFetch, getMe } from "@/lib/server/api";

export const metadata: Metadata = { title: "Quote" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Printable quote (use the browser's "Save as PDF"). Customers get the portal view of the
 * quote, staff the staff view - both through the API, so each sees only what they may.
 * Internal notes and approval details are never printed.
 */
export default async function PrintQuotePage({
  params,
}: PageProps<"/print/quotes/[id]">) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  const me = await getMe();
  const customer = me.user_type === "customer";
  let quote: Quote | PortalQuote;
  try {
    quote = await apiFetch<Quote | PortalQuote>(
      customer ? `/portal/quotes/${id}` : `/quotes/${id}`,
    );
  } catch (error) {
    if (
      error instanceof ApiError &&
      (error.status === 404 || error.status === 403)
    )
      notFound();
    throw error;
  }
  if (
    quote.status === "draft" ||
    quote.status === "pending_approval" ||
    quote.status === "superseded"
  )
    notFound(); // only released quotes are printed
  const account = await apiFetch<PortalAccount | { name: string }>(
    customer
      ? `/portal/accounts/${quote.account_id}`
      : `/accounts/${quote.account_id}`,
  ).catch(() => null);

  return (
    <main className="mx-auto max-w-4xl bg-white p-8 text-slate-900 print:p-0">
      <div className="mb-6 flex justify-end print:hidden">
        <PrintButton />
      </div>
      <header className="flex flex-wrap items-start justify-between gap-6 border-b border-slate-300 pb-6">
        <div>
          <p className="text-sm uppercase tracking-wide text-slate-500">Quote</p>
          <h1 className="text-2xl font-semibold">{quoteNumber(quote.number, quote.revision)}</h1>
          <p className="mt-1 text-lg">{quote.title}</p>
        </div>
        <div className="text-right text-sm">
          <p className="font-semibold">{me.tenant_name ?? "Your supplier"}</p>
          <p className="mt-3 text-slate-600">For</p>
          <p className="font-medium">{account?.name ?? "Customer"}</p>
        </div>
      </header>
      <dl className="my-6 grid grid-cols-2 gap-4 text-sm sm:grid-cols-3">
        <div><dt className="text-slate-500">Date</dt><dd>{formatDate(quote.sent_at ?? quote.created_at)}</dd></div>
        <div><dt className="text-slate-500">Valid until</dt><dd>{formatDate(quote.valid_until)}{quote.expired && " (expired)"}</dd></div>
        <div><dt className="text-slate-500">Currency</dt><dd>{quote.currency}</dd></div>
      </dl>
      <QuoteLinesTable lines={quote.lines} currency={quote.currency} />
      <QuoteTotals quote={quote} />
      {quote.customer_note && (
        <section className="mt-6 border-t border-slate-200 pt-4 text-sm">
          <h2 className="font-semibold">Notes</h2>
          <p className="whitespace-pre-line text-slate-700">{quote.customer_note}</p>
        </section>
      )}
      <footer className="mt-10 border-t border-slate-200 pt-4 text-xs text-slate-500">
        Prices exclude tax unless shown otherwise. This quote is valid until {formatDate(quote.valid_until)}.
      </footer>
    </main>
  ); // prettier-ignore
}
