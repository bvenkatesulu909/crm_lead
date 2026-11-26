/**
 * Research many accounts at once (ADR 0042): the shapes the API returns and the words the screens
 * use. Display only - who may start, which accounts are in a batch and what it may cost are all
 * decided by the API again.
 */

import type { ApiErrorInfo } from "@/lib/api-error";

export const MAX_BATCH_ACCOUNTS = 100;

export type BatchSource = "filter" | "rows";
export type RetryWhich = "failed" | "not_run" | "both";
export type BatchStatus =
  "running" | "finished" | "cancelled" | "stopped_budget" | "stopped_error";
export type ItemStatus =
  "queued" | "running" | "done" | "reused" | "skipped" | "failed" | "not_run";

/** What the browser sends to ask for an estimate or start: which accounts, nothing else. */
export type BatchSelection = {
  source: BatchSource;
  saved_filter_id: string | null;
  account_ids: string[];
  research_again: boolean;
};

export type BatchEstimate = {
  accounts: number;
  not_available: number;
  archived: number;
  reused: number;
  calling_model: number;
  upper_bound_tokens: number;
  typical_tokens: number;
  estimated_cost_usd: string | null;
  cap_tokens: number;
  monthly_tokens_left: number | null;
  daily_left: number;
  worst_case_tokens_per_account: number;
};

export type Batch = {
  id: string;
  status: BatchStatus;
  source: BatchSource;
  saved_filter_id: string | null;
  account_count: number;
  not_available_count: number;
  archived_count: number;
  estimated_upper_tokens: number;
  estimated_cost_usd: string | null;
  token_cap: number;
  tokens_used: number;
  research_again: boolean;
  cancel_requested: boolean;
  created_by_user_id: string;
  mine: boolean;
  version: number;
  created_at: string;
  finished_at: string | null;
  counts: Partial<Record<ItemStatus, number>>;
};

export type BriefFigures = {
  brief_id: string;
  created_at: string;
  sentences: number;
  dropped: number;
  gathered: Record<string, number>;
  tokens: number;
};

export type BatchItem = {
  position: number;
  account_id: string;
  account_name: string | null;
  status: ItemStatus;
  failure_code: string | null;
  brief_id: string | null;
  input_tokens: number;
  output_tokens: number;
  brief: BriefFigures | null;
};

export type BatchDetail = Batch & { items: BatchItem[] };

export type BatchPage = {
  items: Batch[];
  total: number;
  limit: number;
  offset: number;
};

/** What an estimate Server Action gives back to the browser. */
export type EstimateResult =
  { ok: true; estimate: BatchEstimate } | { ok: false; error: ApiErrorInfo };

/** What a start Server Action gives back when it did NOT start (a start redirects). */
export type StartFailed = { error: ApiErrorInfo };

export const BATCH_STATUS_LABELS: Record<BatchStatus, string> = {
  running: "Running",
  finished: "Finished",
  cancelled: "Stopped by a person",
  stopped_budget: "Stopped: the AI budget or a switch",
  stopped_error: "Stopped: an error",
};

export const ITEM_STATUS_LABELS: Record<ItemStatus, string> = {
  queued: "Waiting",
  running: "Being researched",
  done: "Researched",
  reused: "Recent brief used",
  skipped: "Skipped",
  failed: "Failed",
  not_run: "Not run",
};

const FAILURE_LABELS: Record<string, string> = {
  no_sourced_sentence: "The AI wrote nothing it could back with a record.",
  answer_refused: "The AI's answer was not in the required form.",
  rate_limited: "This account was researched less than an hour ago.",
  unavailable: "The AI could not be reached (tried three times).",
  error: "Something went wrong while this account was researched.",
};

/** A failed account's reason in plain words (an unknown code still says something). */
export function failureText(code: string | null): string {
  if (code === null) return "";
  return FAILURE_LABELS[code] ?? "It could not be researched.";
}

/** Messages for the refusals a person can do something about; the rest uses the API's words. */
const ERROR_TEXT: Record<string, string> = {
  empty_selection:
    "None of these accounts can be researched by you. Tick accounts you can open, or choose another filter.",
  batch_too_large: `A batch holds at most ${MAX_BATCH_ACCOUNTS} accounts. Narrow the filter or tick fewer accounts.`,
  estimate_changed:
    "The cost changed since you looked at it. Look at the new estimate before you start.",
  agent_unavailable:
    "Researching many accounts is switched off. An administrator can switch it on under AI agents (both account research and research batches must be on).",
  agent_budget_reached:
    "This month's AI budget for account research is used up. An administrator can raise it under AI agents.",
  research_budget_too_small:
    "This month's AI budget for account research is too small for even one account.",
  research_batch_limit:
    "You have started the most batches allowed for now. Try again later.",
  research_daily_limit:
    "Today's limit for researched accounts is reached. Try again tomorrow.",
  research_batch_running:
    "This batch is still running. Wait for it to end, or stop it first.",
  research_batch_not_running: "This batch is not running any more.",
  research_batch_not_found: "This batch does not exist, or you may not see it.",
};

export function batchErrorText(error: Pick<ApiErrorInfo, "code" | "message">) {
  return (error.code && ERROR_TEXT[error.code]) || error.message;
}

export function isRunning(batch: Pick<Batch, "status">): boolean {
  return batch.status === "running";
}

/** How far the batch is: accounts that ended (whatever the result) out of all of them. */
export function progress(batch: Pick<Batch, "account_count" | "counts">) {
  const waiting = (batch.counts.queued ?? 0) + (batch.counts.running ?? 0);
  const total = batch.account_count;
  const ended = Math.max(0, total - waiting);
  const percent = total === 0 ? 100 : Math.round((ended / total) * 100);
  return { ended, total, percent };
}

/** The accounts a retry could try again; 0 while the batch runs (the API refuses then). */
export function retryable(batch: Pick<Batch, "status" | "counts">): {
  failed: number;
  notRun: number;
} {
  if (isRunning(batch)) return { failed: 0, notRun: 0 };
  return {
    failed: batch.counts.failed ?? 0,
    notRun: batch.counts.not_run ?? 0,
  };
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const isUuid = (value: unknown): value is string =>
  typeof value === "string" && UUID.test(value);

/**
 * Check a selection that came from the browser before it is sent on: a known source, ids that
 * look like ids (at most a few hundred - the API refuses more than a batch holds with a clear
 * message), and nothing else. Returns null when it cannot be a selection at all.
 */
export function cleanSelection(input: unknown): BatchSelection | null {
  if (typeof input !== "object" || input === null) return null;
  const raw = input as Record<string, unknown>;
  const ids = Array.isArray(raw.account_ids) ? raw.account_ids : [];
  if (ids.length > 500 || !ids.every(isUuid)) return null;
  const again = raw.research_again === true;
  if (raw.source === "filter") {
    if (!isUuid(raw.saved_filter_id)) return null;
    return {
      source: "filter",
      saved_filter_id: raw.saved_filter_id,
      account_ids: [],
      research_again: again,
    };
  }
  if (raw.source === "rows") {
    if (ids.length === 0) return null;
    return {
      source: "rows",
      saved_filter_id: null,
      account_ids: [...new Set(ids as string[])],
      research_again: again,
    };
  }
  return null;
}

export function cleanWhich(value: unknown): RetryWhich | null {
  return value === "failed" || value === "not_run" || value === "both"
    ? value
    : null;
}

/** The confirmed figure the person was shown: a whole, non-negative number of tokens. */
export function cleanConfirmed(value: unknown): number | null {
  return typeof value === "number" &&
    Number.isInteger(value) &&
    value >= 0 &&
    value <= 100_000_000
    ? value
    : null;
}

/** What the gatherers found, for the table ("2 sales, 1 service"). */
export function gatheredText(gathered: Record<string, number>): string {
  const parts = Object.entries(gathered)
    .filter(([, count]) => count > 0)
    .map(([source, count]) => `${count} ${source}`);
  return parts.length === 0 ? "nothing" : parts.join(", ");
}
