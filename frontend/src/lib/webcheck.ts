import type { WebEvidenceVerdict } from "@/lib/api-types";
import { isUuid } from "@/lib/communications";

/**
 * Web check helpers (ADR 0019) that need no server: plain words for what came back, what went
 * wrong and what was cleaned, and the check of the form before it is sent. The API decides
 * everything again - who may ask, which sources exist, what a valid query looks like.
 */

export type WebCheckRecord = { type: "lead" | "account"; id: string };

const RECORD_PATHS: Record<WebCheckRecord["type"], string> = {
  lead: "/leads",
  account: "/accounts",
};

/** The page of the record (also where the form goes back to). Throws for a tampered record. */
export function webCheckPath(record: WebCheckRecord): string {
  if (!(record.type in RECORD_PATHS) || !isUuid(record.id))
    throw new Error("invalid record");
  return `${RECORD_PATHS[record.type]}/${record.id}`;
}

const VERDICT_LABELS: Record<WebEvidenceVerdict, string> = {
  found: "Found",
  not_found: "Not found",
  unclear: "Could not be read with certainty",
  error: "Could not be checked",
};

export function verdictLabel(verdict: string): string {
  return VERDICT_LABELS[verdict as WebEvidenceVerdict] ?? verdict;
}

const STATUS_LABELS: Record<string, string> = {
  active: "Active",
  expired: "Expired",
  revoked: "Revoked",
  suspended: "Suspended",
  lapsed: "Lapsed",
  struck_off: "Struck off",
  dormant: "Dormant",
  liquidation: "In liquidation",
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status.replaceAll("_", " ");
}

const ERROR_TEXTS: Record<string, string> = {
  robots_disallowed:
    "The site's rules (robots.txt) do not allow this page to be read automatically.",
  robots_unavailable: "The site's rules (robots.txt) could not be read.",
  timeout: "The site did not answer in time.",
  network_error: "The site could not be reached.",
  rate_limited: "Too many requests were made to this site; try again later.",
  private_address:
    "The site's address is not a public one, so it was not contacted.",
  no_address: "The site's name could not be found.",
  too_large: "The page was larger than the limit.",
  bad_content_type: "The page was not a kind of page that is allowed.",
  bad_encoding: "The page was encoded in a way that is not allowed.",
  bad_redirect: "The site sent the check somewhere that is not allowed.",
  too_many_redirects: "The site sent the check around too many times.",
  bad_host: "The site sent the check somewhere that is not allowed.",
  source_unavailable: "This source was switched off before the check ran.",
  invalid_query: "The search text was not in a valid shape.",
};

/** Why a check could not be made (the evidence's error code), with a fallback. */
export function errorText(code: string | null | undefined): string {
  return (code && ERROR_TEXTS[code]) || "The check could not be made.";
}

const REQUEST_ERRORS: Record<string, string> = {
  webcheck_limit_reached:
    "You have asked for many checks recently. Try again in a while.",
  webcheck_disabled: "The web check is switched off.",
  source_unavailable: "This source is not available.",
  record_not_found: "You can't see this record, so you can't check it.",
};

/** Why asking for a check was refused, or null to use the server's own sentence. */
export function requestErrorText(
  code: string | null | undefined,
): string | null {
  return (code && REQUEST_ERRORS[code]) || null;
}

const CLEANED_TEXTS: Record<string, string> = {
  link: "a link was removed",
  external_image: "an image was removed",
  hidden_characters: "hidden characters were removed",
  instruction_phrase:
    "text that reads like an instruction to an AI was kept and flagged",
  html_markup: "markup was removed",
  email_address: "an e-mail address was removed",
  repeated_text: "repeated text was shortened",
  control_characters: "control characters were removed",
};

/** What was cleaned in the page's text, in words (codes we do not know are left out). */
export function cleanedNotes(codes: string[]): string[] {
  return codes.flatMap((code) =>
    CLEANED_TEXTS[code] ? [CLEANED_TEXTS[code]] : [],
  );
}

export const QUERY_MAX = 200;

export type CheckRequestResult =
  | { ok: true; data: { source_key: string; query: string } }
  | { ok: false; fieldErrors: Record<string, string> };

/** A first check before the request leaves the browser; the API checks the shape for real. */
export function checkRequest(input: {
  sourceKey: string;
  query: string;
}): CheckRequestResult {
  const fieldErrors: Record<string, string> = {};
  const query = input.query.trim();
  if (!input.sourceKey) fieldErrors.source_key = "Choose where to look.";
  if (!query) fieldErrors.query = "Enter the number or name to look up.";
  else if (query.length > QUERY_MAX)
    fieldErrors.query = `Please keep it under ${QUERY_MAX} characters.`;
  if (Object.keys(fieldErrors).length > 0) return { ok: false, fieldErrors };
  return { ok: true, data: { source_key: input.sourceKey, query } };
}
