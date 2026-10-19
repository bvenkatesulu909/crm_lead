import type { QuoteStatus } from "@/lib/api-types";

/** Quote labels and the PREVIEW of quote money (the server calculates the real amounts). */

export const QUOTE_STATUS_LABELS: Record<QuoteStatus, string> = {
  draft: "Draft",
  pending_approval: "Waiting for approval",
  approved: "Approved",
  sent: "Sent to customer",
  accepted: "Accepted",
  declined: "Declined",
  superseded: "Replaced by a newer revision",
};

export const QUOTE_STATUS_STYLE: Record<QuoteStatus, string> = {
  draft: "bg-slate-100 text-slate-700",
  pending_approval: "bg-amber-50 text-amber-800",
  approved: "bg-sky-50 text-sky-800",
  sent: "bg-brand-50 text-brand-700",
  accepted: "bg-emerald-50 text-emerald-700",
  declined: "bg-red-50 text-red-700",
  superseded: "bg-slate-100 text-slate-500",
};

/** "QT-0007" for the first version, "QT-0007 rev 2" for later revisions. */
export function quoteNumber(number: number, revision = 1): string {
  const base = `QT-${String(number).padStart(4, "0")}`;
  return revision > 1 ? `${base} rev ${revision}` : base;
}

// Same rule as the API (quotes/rules.py): above this discount a manager must approve.
/** Used until the organisation's own limit is loaded (GET /quotes/settings). */
export const DEFAULT_APPROVAL_LIMIT = 10;

/** Cents, rounded half up - the same rounding as the API. Works on strings to avoid float drift. */
function cents(value: number): number {
  return Math.sign(value) * Math.round(Math.abs(value) * 100 + 1e-9);
}

export type PreviewLine = {
  quantity: number;
  listPrice: number;
  discountPercent: number;
  taxRate: number;
};

export type Preview = {
  gross: number;
  discount: number;
  subtotal: number;
  tax: number;
  total: number;
  needsApproval: boolean;
};

/** Mirrors quotes/rules.py: the discount is applied to the unit price, rounded per line. */
export function previewTotals(
  lines: PreviewLine[],
  approvalLimit: number = DEFAULT_APPROVAL_LIMIT,
): Preview {
  let gross = 0;
  let subtotal = 0;
  let tax = 0;
  for (const l of lines) {
    const net = cents((l.listPrice * (100 - l.discountPercent)) / 100);
    const lineGross = cents(l.quantity * l.listPrice);
    const lineSub = cents(l.quantity * (net / 100));
    gross += lineGross;
    subtotal += lineSub;
    tax += cents(((lineSub / 100) * l.taxRate) / 100);
  }
  return {
    gross: gross / 100,
    discount: (gross - subtotal) / 100,
    subtotal: subtotal / 100,
    tax: tax / 100,
    total: (subtotal + tax) / 100,
    needsApproval: lines.some((l) => l.discountPercent > approvalLimit),
  };
}

/** Default "valid until" for a new quote: 30 days from `now` (YYYY-MM-DD, UTC). */
export function defaultValidUntil(now: Date = new Date()): string {
  return new Date(now.getTime() + 30 * 86_400_000).toISOString().slice(0, 10);
}
