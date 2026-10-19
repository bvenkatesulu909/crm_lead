import { buttonClass, cx } from "@/components/ui";
import type { QuoteLine, QuoteStatus } from "@/lib/api-types";
import { formatAmounts } from "@/lib/dashboard";
import { QUOTE_STATUS_LABELS, QUOTE_STATUS_STYLE } from "@/lib/quotes";

const m = (amount: string, currency: string) =>
  formatAmounts([{ currency, amount }]);
const qty = (q: string) => q.replace(/\.?0+$/, "");

export function QuoteStatusBadge({
  status,
  expired,
}: {
  status: QuoteStatus;
  expired?: boolean;
}) {
  return (
    <span className="inline-flex flex-wrap gap-1">
      <span className={cx("rounded-full px-2.5 py-0.5 text-xs font-medium", QUOTE_STATUS_STYLE[status])}>
        {QUOTE_STATUS_LABELS[status]}
      </span>
      {expired && <span className="rounded-full bg-red-50 px-2.5 py-0.5 text-xs font-medium text-red-700">Expired</span>}
    </span>
  ); // prettier-ignore
}

/** Quote lines with list price, discount and net amounts (same for staff, portal and print). */
export function QuoteLinesTable({
  lines,
  currency,
}: {
  lines: QuoteLine[];
  currency: string;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-600 print:bg-white">
          <tr>
            <th scope="col" className="px-4 py-2">#</th>
            <th scope="col" className="px-4 py-2">Item</th>
            <th scope="col" className="px-4 py-2 text-right">Qty</th>
            <th scope="col" className="px-4 py-2 text-right">List price</th>
            <th scope="col" className="px-4 py-2 text-right">Discount</th>
            <th scope="col" className="px-4 py-2 text-right">Net price</th>
            <th scope="col" className="px-4 py-2 text-right">Tax</th>
            <th scope="col" className="px-4 py-2 text-right">Amount</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {lines.map((l) => (
            <tr key={l.position}>
              <td className="px-4 py-2 text-slate-500">{l.position}</td>
              <td className="px-4 py-2">
                <span className="font-medium text-slate-900">{l.description}</span>
                <span className="block font-mono text-xs text-slate-500">{l.sku}</span>
              </td>
              <td className="px-4 py-2 text-right whitespace-nowrap">{qty(l.quantity)} {l.unit}</td>
              <td className="px-4 py-2 text-right whitespace-nowrap">{m(l.list_price, currency)}</td>
              <td className="px-4 py-2 text-right whitespace-nowrap">{Number(l.discount_percent) > 0 ? `${Number(l.discount_percent)} %` : "—"}</td>
              <td className="px-4 py-2 text-right whitespace-nowrap">{m(l.net_unit_price, currency)}</td>
              <td className="px-4 py-2 text-right whitespace-nowrap">{Number(l.tax_rate)} %</td>
              <td className="px-4 py-2 text-right whitespace-nowrap font-medium">{m(l.line_subtotal, currency)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ); // prettier-ignore
}

export function QuoteTotals({
  quote,
}: {
  quote: {
    currency: string;
    gross_total: string;
    discount_total: string;
    subtotal: string;
    tax_total: string;
    total: string;
  };
}) {
  const c = quote.currency;
  return (
    <dl className="ml-auto w-full max-w-xs space-y-1 px-4 py-3 text-sm">
      <div className="flex justify-between"><dt className="text-slate-600">List value</dt><dd>{m(quote.gross_total, c)}</dd></div>
      {Number(quote.discount_total) > 0 && (
        <div className="flex justify-between"><dt className="text-slate-600">Discount</dt><dd>− {m(quote.discount_total, c)}</dd></div>
      )}
      <div className="flex justify-between"><dt className="text-slate-600">Net</dt><dd>{m(quote.subtotal, c)}</dd></div>
      <div className="flex justify-between"><dt className="text-slate-600">Tax</dt><dd>{m(quote.tax_total, c)}</dd></div>
      <div className="flex justify-between border-t border-slate-200 pt-1 text-base font-semibold"><dt>Total</dt><dd>{m(quote.total, c)}</dd></div>
    </dl>
  ); // prettier-ignore
}

/**
 * Download of the stored PDF (a plain link: a file download must not be prefetched).
 * The route handler fetches it from the API on the server, so no token reaches the browser.
 */
export function PdfDownload({ href }: { href: string }) {
  return (
    <a href={href} download className={buttonClass("secondary")}>
      Download PDF
    </a>
  );
}

const FILE_PROBLEMS: Record<string, string> = {
  missing: "The PDF couldn't be found.",
  "not-sent": "A PDF is available once the quote has been sent.",
  unavailable:
    "The file store is temporarily unavailable. Please try again shortly.",
};

/** Message after a failed download (the route handler sends the user back with ?file=…). */
export function FileProblem({ reason }: { reason: unknown }) {
  const text = typeof reason === "string" ? FILE_PROBLEMS[reason] : undefined;
  if (!text) return null;
  return (
    <div role="alert" className="mb-4 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
      {text}
    </div>
  ); // prettier-ignore
}
