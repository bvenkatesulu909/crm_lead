/**
 * Deal desk helpers (ADR 0024) that need no server: the shapes the API returns, its codes in plain
 * words, and where each cited record lives. The API decides everything again - who may ask, the
 * limits, what a reviewer may cite.
 */
import { isUuid } from "@/lib/communications";

export type DealDeskReviewer = "pricing" | "account" | "momentum";
export type DealDeskSeverity = "info" | "watch" | "act";
export type CitedRecordType = "opportunity" | "quote" | "account" | "contract";

export type DealDeskFinding = {
  reviewer: DealDeskReviewer;
  severity: DealDeskSeverity;
  /** Written by a model and cleaned by the API: shown as plain text only. */
  text: string;
  records: { type: CitedRecordType; id: string }[];
};

export type DealDeskReview = {
  id: string;
  opportunity_id: string;
  created_at: string;
  /** Written by a model and cleaned by the API: shown as plain text only. */
  brief: string;
  findings: DealDeskFinding[];
  reviewers: Partial<Record<DealDeskReviewer, "answered" | "refused">>;
  proposals: { id: string; link: string }[];
};

export const REVIEWER_LABELS: Record<DealDeskReviewer, string> = {
  pricing: "Pricing",
  account: "Account",
  momentum: "Momentum",
};

export const SEVERITY_LABELS: Record<DealDeskSeverity, string> = {
  act: "Needs action",
  watch: "Keep an eye on",
  info: "For information",
};

const ERROR_TEXTS: Record<string, string> = {
  deal_not_found: "Deal not found.",
  deal_desk_owner_only:
    "Only the deal's owner or a manager can ask the deal desk about this deal.",
  deal_desk_no_answer:
    "None of the reviewers gave a usable answer. Nothing was stored. Please try again later.",
  deal_desk_invalid_answer:
    "The desk lead did not give a usable answer. Nothing was stored. Please try again later.",
  agent_unavailable:
    "The deal desk is switched off. An administrator can switch it on under AI agents.",
  agent_budget_reached: "The deal desk has reached its limit for this month.",
  assistant_unavailable: "The assistant is not available right now.",
};

/** A code from the API in plain words; the API's own text when it has no special wording (a
 * limit, for example, already comes with its own sentence). */
export function dealDeskErrorText(
  code: string | undefined | null,
  fallback: string,
): string {
  return (code && ERROR_TEXTS[code]) || fallback;
}

const PATHS: Record<CitedRecordType, string> = {
  opportunity: "opportunities",
  quote: "quotes",
  account: "accounts",
  contract: "contracts",
};

/** Where a cited record lives - only for a known kind and a well-formed id (the ids come from the
 * API, but a link is built here, so it is checked here). */
export function recordLink(type: string, id: string): string | null {
  const path = PATHS[type as CitedRecordType];
  return path && isUuid(id) ? `/${path}/${id}` : null;
}

export const RECORD_LABELS: Record<CitedRecordType, string> = {
  opportunity: "this deal",
  quote: "quote",
  account: "account",
  contract: "contract",
};

export function opportunityPath(opportunityId: string): string {
  if (!isUuid(opportunityId)) throw new Error("invalid deal");
  return `/opportunities/${opportunityId}`;
}

/** Proposal links point into the approval queue, nowhere else. */
export function proposalLink(link: string): string | null {
  const id = link.startsWith("/approvals/")
    ? link.slice("/approvals/".length)
    : "";
  return isUuid(id) ? `/approvals/${id}` : null;
}

// --- account research (DD4) ----------------------------------------------------------------------

export type AccountBriefSentence = {
  /** Written by a model and cleaned by the API: shown as plain text only. */
  text: string;
  records: { type: "opportunity" | "account" | "contract"; id: string }[];
};

export type AccountBrief = {
  id: string;
  account_id: string;
  created_at: string;
  sentences: AccountBriefSentence[];
  /** Sentences removed for naming no source the writer was given. */
  dropped: number;
  gathered: Partial<
    Record<"sales" | "service" | "conversations" | "registry", number>
  >;
};

const RESEARCH_ERRORS: Record<string, string> = {
  account_not_found: "Account not found.",
  account_research_invalid_answer:
    "The assistant did not write a usable brief. Nothing was stored. Please try again later.",
  agent_unavailable:
    "Account research is switched off. An administrator can switch it on under AI agents.",
  agent_budget_reached:
    "Account research has reached its limit for this month.",
  assistant_unavailable: "The assistant is not available right now.",
};

export function researchErrorText(
  code: string | undefined | null,
  fallback: string,
): string {
  return (code && RESEARCH_ERRORS[code]) || fallback;
}

export function accountPath(accountId: string): string {
  if (!isUuid(accountId)) throw new Error("invalid account");
  return "/accounts/" + accountId;
}
