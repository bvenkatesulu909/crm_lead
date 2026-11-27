/**
 * Deal risk forecast helpers (ADR 0037) that need no server: the shapes the API returns, its codes
 * in plain words, the colours of the three levels and the sums for the dashboard. The API decides
 * everything again - who may see a forecast and what it says. A forecast is an estimate from the
 * listed reasons: never show the score as a probability or as a fact.
 */
import { isUuid } from "@/lib/communications";

export type RiskLevel = "low" | "medium" | "high";

export type RiskFactor = {
  code: string;
  /** Worked out by the server from fixed words and numbers: plain text. */
  sentence: string;
  points: number;
  /** The kind of record the reason comes from, e.g. "activities". */
  source: string;
};

export type RiskDeal = {
  id: string;
  name: string;
  account_id: string;
  stage: string;
  amount: string | null;
  currency: string;
};

export type DealRisk = {
  id: string;
  opportunity_id: string;
  level: RiskLevel;
  score: number;
  rules_version: number;
  source: "nightly" | "on_demand";
  computed_at: string;
  factors: RiskFactor[];
  /** Signals the server could not read; they add no points and are never good news. */
  unknown: string[];
  note: string;
  deal: RiskDeal | null;
};

export type DealRiskList = {
  items: DealRisk[];
  total: number;
  limit: number;
  offset: number;
  note: string;
};

export type DealRiskHistoryItem = Omit<DealRisk, "deal">;

export const LEVEL_LABELS: Record<RiskLevel, string> = {
  low: "Low risk",
  medium: "Medium risk",
  high: "High risk",
};

/** Words, not only colours: the level is always written out. */
export const LEVEL_STYLES: Record<RiskLevel, string> = {
  low: "bg-emerald-50 text-emerald-800",
  medium: "bg-amber-50 text-amber-800",
  high: "bg-red-50 text-red-700",
};

export const isRiskLevel = (value: string | undefined): value is RiskLevel =>
  value === "low" || value === "medium" || value === "high";

/** What each "could not be read" code means, in plain words. */
const UNKNOWN_TEXTS: Record<string, string> = {
  last_activity: "when anything last happened on the deal",
  tasks: "the follow-up tasks",
  account_health: "the customer account's health",
  typical_stage_time:
    "how long won deals usually spend in this stage (too few won deals yet)",
};

export function unknownText(code: string): string {
  return UNKNOWN_TEXTS[code] ?? code.replaceAll("_", " ");
}

const ERROR_TEXTS: Record<string, string> = {
  deal_not_found: "Deal not found.",
  deal_risk_rate_limited:
    "You have asked for too many forecasts this hour. Try again later.",
  deal_risk_not_allowed: "You may not see deal risk.",
};

/** A code from the API in plain words; the API's own text when it has no special wording. */
export function dealRiskErrorText(
  code: string | undefined | null,
  fallback: string,
): string {
  return (code && ERROR_TEXTS[code]) || fallback;
}

/** The newest forecast per deal, by deal id (for badges on the pipeline). */
export function riskByDeal(items: DealRisk[]): Record<string, DealRisk> {
  const map: Record<string, DealRisk> = {};
  for (const item of items) {
    // The list holds one forecast per deal; keep the first if a repeat ever appears.
    if (!(item.opportunity_id in map)) map[item.opportunity_id] = item;
  }
  return map;
}

// BigInt() instead of `100n` literals: the project compiles for ES2017.
const ZERO = BigInt(0);
const ONE = BigInt(1);
const HUNDRED = BigInt(100);

/** Whole cents of a decimal string such as "1200.50" (money is never a float). */
function cents(amount: string): bigint | null {
  const match = /^(-?)(\d+)(?:\.(\d{1,2}))?\d*$/.exec(amount.trim());
  if (!match) return null;
  const sign = match[1] === "-" ? -ONE : ONE;
  const fraction = (match[3] ?? "").padEnd(2, "0");
  return sign * (BigInt(match[2]) * HUNDRED + BigInt(fraction));
}

/** Plain sums of the deals' amounts per currency, with no conversion and no weighting. */
export function sumByCurrency(
  items: Pick<DealRisk, "deal">[],
): { currency: string; amount: string }[] {
  const totals = new Map<string, bigint>();
  for (const { deal } of items) {
    if (!deal || deal.amount === null) continue;
    const value = cents(deal.amount);
    if (value === null) continue;
    totals.set(deal.currency, (totals.get(deal.currency) ?? ZERO) + value);
  }
  return [...totals.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([currency, total]) => ({
      currency,
      amount: `${total / HUNDRED}.${(total % HUNDRED).toString().padStart(2, "0")}`,
    }));
}

/** "Was medium on 14 Nov" - how the level moved since the previous forecast, or null. */
export function levelChange(
  history: Pick<DealRiskHistoryItem, "level" | "score" | "computed_at">[],
): { from: RiskLevel; at: string; moved: boolean } | null {
  // History is newest first; the second entry is the forecast before the current one.
  const previous = history[1];
  if (!previous) return null;
  return {
    from: previous.level,
    at: previous.computed_at,
    moved: previous.level !== history[0].level,
  };
}

export function opportunityPath(opportunityId: string): string {
  if (!isUuid(opportunityId)) throw new Error("invalid deal");
  return `/opportunities/${opportunityId}`;
}
