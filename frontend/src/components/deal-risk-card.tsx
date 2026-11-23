import { updateDealRisk } from "@/app/(app)/deal-risk/actions";
import { UpdateDealRiskButton } from "@/components/deal-risk-button";
import { RiskBadge } from "@/components/risk-badge";
import { Card } from "@/components/ui";
import type { Me } from "@/lib/api-types";
import {
  LEVEL_LABELS,
  levelChange,
  unknownText,
  type DealRisk,
  type DealRiskHistoryItem,
} from "@/lib/deal-risk";
import { formatDate, formatDateTime } from "@/lib/format";
import { canReadDealRisk } from "@/lib/permissions";
import { ApiError } from "@/lib/api-error";
import { apiFetch } from "@/lib/server/api";

/** The newest forecast as plain text: the level, the reasons and what could not be read. */
export function DealRiskView({
  risk,
  history,
}: {
  risk: DealRisk;
  history: DealRiskHistoryItem[];
}) {
  const change = levelChange(history);
  return (
    <div className="space-y-3">
      <p className="flex flex-wrap items-center gap-2 text-sm text-slate-900">
        <RiskBadge level={risk.level} />
        <span>
          {risk.factors.length === 0
            ? "No warning signs were found."
            : "Why this forecast:"}
        </span>
      </p>
      {risk.factors.length > 0 && (
        <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">
          {risk.factors.map((f) => (
            <li key={f.code}>
              {f.sentence}{" "}
              <span className="text-xs text-slate-500">
                (+{f.points}, {f.source})
              </span>
            </li>
          ))}
        </ul>
      )}
      {risk.unknown.length > 0 && (
        <p className="text-xs text-slate-600">
          Could not be read (counted as unknown, not as good news):{" "}
          {risk.unknown.map(unknownText).join("; ")}.
        </p>
      )}
      {change && (
        <p className="text-xs text-slate-600">
          {change.moved
            ? `It was ${LEVEL_LABELS[change.from].toLowerCase()} on ${formatDate(change.at)}.`
            : `Unchanged since ${formatDate(change.at)}.`}
        </p>
      )}
      <p className="text-xs text-slate-500">
        Worked out {formatDateTime(risk.computed_at)} (
        {risk.source === "nightly" ? "daily run" : "on request"}). {risk.note}
      </p>
    </div>
  );
}

/**
 * The risk forecast on a deal page (ADR 0037) for sales managers and administrators. Like the
 * other extra cards it is information - the page works without it. The API decides again.
 */
export async function DealRiskCard({
  me,
  opportunity,
}: {
  me: Pick<Me, "permissions">;
  opportunity: { id: string; is_open: boolean };
}) {
  if (!canReadDealRisk(me) || !opportunity.is_open) return null;
  const latest = await apiFetch<DealRisk>(`/deal-risk/${opportunity.id}`).catch(
    (error) =>
      error instanceof ApiError && error.status === 404 ? null : undefined,
  );
  if (latest === undefined) return null; // the forecast could not be loaded: leave the card out
  const history = latest
    ? await apiFetch<{ items: DealRiskHistoryItem[] }>(
        `/deal-risk/${opportunity.id}/history?limit=2`,
      )
        .then((h) => h.items)
        .catch(() => [])
    : [];
  return (
    <Card id="deal-risk" aria-labelledby="deal-risk-heading" className="p-5">
      <h2
        id="deal-risk-heading"
        className="text-base font-semibold text-slate-900"
      >
        Deal risk forecast
      </h2>
      <div className="mt-3 space-y-4">
        {latest ? (
          <DealRiskView risk={latest} history={history} />
        ) : (
          <p className="text-sm text-slate-600">
            No forecast has been worked out for this deal yet.
          </p>
        )}
        <UpdateDealRiskButton
          action={updateDealRisk.bind(null, opportunity.id)}
          hasForecast={latest !== null}
        />
        <p className="text-xs text-slate-500">
          A forecast is an estimate from the reasons listed, not a promise. It
          is worked out by fixed rules from this deal&apos;s records; no AI
          decides it.
        </p>
      </div>
    </Card>
  );
}
