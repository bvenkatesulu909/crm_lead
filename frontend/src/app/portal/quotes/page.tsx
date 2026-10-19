import type { Metadata } from "next";
import Link from "next/link";

import { QuoteStatusBadge } from "@/components/quote-view";
import { Card, EmptyState, ErrorAlert } from "@/components/ui";
import { toErrorInfo } from "@/lib/api-error";
import type { PortalQuotePage } from "@/lib/api-types";
import { formatAmounts } from "@/lib/dashboard";
import { formatDate } from "@/lib/format";
import { quoteNumber } from "@/lib/quotes";
import { apiFetch } from "@/lib/server/api";

export const metadata: Metadata = { title: "Quotes" };

/** Quotes sent to the customer's company (never drafts or internal details). */
export default async function PortalQuotesPage() {
  let data: PortalQuotePage;
  try {
    data = await apiFetch<PortalQuotePage>("/portal/quotes");
  } catch (error) {
    return (
      <ErrorAlert
        title="Your quotes could not be loaded"
        error={toErrorInfo(error)}
      />
    );
  }
  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link href="/portal" className="font-medium text-brand-700 hover:underline">← Portal home</Link>
      </nav>
      <h1 className="mb-6 text-2xl font-semibold tracking-tight text-slate-900">Quotes</h1>
      <Card>
        {data.items.length === 0 ? (
          <EmptyState title="No quotes yet" description="Quotes we send you appear here." />
        ) : (
          <ul className="divide-y divide-slate-100">
            {data.items.map((q) => (
              <li key={q.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
                <div>
                  <Link href={`/portal/quotes/${q.id}`} className="font-medium text-brand-700 hover:underline">
                    {quoteNumber(q.number, q.revision)} · {q.title}
                  </Link>
                  <p className="text-xs text-slate-500">Valid until {formatDate(q.valid_until)}</p>
                </div>
                <div className="flex items-center gap-3">
                  <span className="font-medium">{formatAmounts([{ currency: q.currency, amount: q.total }])}</span>
                  <QuoteStatusBadge status={q.status} expired={q.expired} />
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  ); // prettier-ignore
}
