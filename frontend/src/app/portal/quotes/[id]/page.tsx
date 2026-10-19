import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import {
  FileProblem,
  PdfDownload,
  QuoteLinesTable,
  QuoteStatusBadge,
  QuoteTotals,
} from "@/components/quote-view";
import { ButtonLink, Card, SuccessAlert } from "@/components/ui";
import { ApiError } from "@/lib/api-error";
import type { PortalQuote } from "@/lib/api-types";
import { formatDate } from "@/lib/format";
import { quoteNumber } from "@/lib/quotes";
import { apiFetch } from "@/lib/server/api";

import { answerQuote } from "../actions";
import { AnswerButtons } from "./answer-buttons";

export const metadata: Metadata = { title: "Quote" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DONE: Record<string, string> = {
  accepted:
    "Thank you! We received your acceptance and will prepare your order.",
  declined: "Thank you for letting us know.",
};

export default async function PortalQuotePage({
  params,
  searchParams,
}: PageProps<"/portal/quotes/[id]">) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  if (!UUID.test(id)) notFound();
  let quote: PortalQuote;
  try {
    quote = await apiFetch<PortalQuote>(`/portal/quotes/${id}`);
  } catch (error) {
    if (
      error instanceof ApiError &&
      (error.status === 404 || error.status === 403)
    )
      notFound();
    throw error;
  }
  const done = typeof query.done === "string" ? DONE[query.done] : undefined;

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link href="/portal/quotes" className="font-medium text-brand-700 hover:underline">← Quotes</Link>
      </nav>
      {done && <div className="mb-4"><SuccessAlert>{done}</SuccessAlert></div>}
      <FileProblem reason={query.file} />
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="font-mono text-sm text-slate-500">{quoteNumber(quote.number, quote.revision)}</p>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{quote.title}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-3 text-sm text-slate-600">
            <QuoteStatusBadge status={quote.status} expired={quote.expired} />
            <span>Valid until {formatDate(quote.valid_until)}</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {quote.status === "sent" && (
            quote.expired ? (
              <p className="max-w-xs text-sm text-slate-600">This quote has expired. Please contact us for an updated offer.</p>
            ) : (
              <AnswerButtons
                accept={answerQuote.bind(null, quote.id, quote.version, true)}
                decline={answerQuote.bind(null, quote.id, quote.version, false)}
              />
            )
          )}
          <ButtonLink href={`/print/quotes/${quote.id}`} variant="secondary">Print</ButtonLink>
          <PdfDownload href={`/portal/quotes/${quote.id}/pdf`} />
        </div>
      </div>
      <Card>
        <QuoteLinesTable lines={quote.lines} currency={quote.currency} />
        <QuoteTotals quote={quote} />
        {quote.customer_note && (
          <p className="whitespace-pre-line border-t border-slate-100 px-5 py-4 text-sm text-slate-700">{quote.customer_note}</p>
        )}
        {quote.decision_note && (
          <p className="border-t border-slate-100 px-5 py-4 text-sm text-slate-600">Your answer: {quote.decision_note}</p>
        )}
      </Card>
    </>
  ); // prettier-ignore
}
