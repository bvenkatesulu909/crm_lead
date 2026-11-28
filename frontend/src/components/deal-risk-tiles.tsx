import Link from "next/link";

import { Card } from "@/components/ui";
import { formatAmounts } from "@/lib/dashboard";
import { sumByCurrency, type DealRiskList } from "@/lib/deal-risk";
import { apiFetch } from "@/lib/server/api";

/**
 * "Deals at high risk" and "Amount at risk" for managers and administrators (ADR 0037). The amount
 * is a plain sum of those deals' values per currency: no conversion and no weighting by chance.
 * Information only - without the forecast (or when it cannot be loaded) nothing is shown.
 */
export async function DealRiskTiles() {
  const high = await apiFetch<DealRiskList>(
    "/deal-risk?level=high&limit=100",
  ).catch(() => null);
  if (!high) return null;
  const more = high.total > high.items.length;
  return (
    <section aria-label="Deal risk forecast" className="mb-6">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
        Deal risk forecast
      </h2>
      <dl className="grid gap-4 sm:grid-cols-2">
        <Card className="p-5">
          <dt className="text-sm font-medium text-slate-600">
            Deals at high risk
          </dt>
          <dd
            className="mt-2 text-2xl font-semibold tracking-tight text-slate-900"
            data-testid="risk-high-count"
          >
            <Link
              href="/opportunities?risk=high"
              className="hover:text-brand-700"
            >
              {high.total}
            </Link>
          </dd>
          <dd className="mt-1 text-xs text-slate-500">
            Open deals whose newest forecast is high. An estimate, not a
            promise.
          </dd>
        </Card>
        <Card className="p-5">
          <dt className="text-sm font-medium text-slate-600">Amount at risk</dt>
          <dd
            className="mt-2 text-2xl font-semibold tracking-tight text-slate-900"
            data-testid="risk-high-amount"
          >
            {formatAmounts(sumByCurrency(high.items))}
          </dd>
          <dd className="mt-1 text-xs text-slate-500">
            {more
              ? `Sum of the first ${high.items.length} of ${high.total} high-risk deals. `
              : ""}
            A plain total per currency: no conversion, not weighted by chance.
          </dd>
        </Card>
      </dl>
    </section>
  );
}
