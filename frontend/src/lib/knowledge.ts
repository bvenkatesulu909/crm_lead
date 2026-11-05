import type { ApiErrorInfo } from "@/lib/api-error";
import type {
  KnowledgeAnswerResponse,
  KnowledgeSearchHit,
} from "@/lib/api-types";

/** Trim a passage to a readable preview (server and client safe). */
export function excerpt(text: string, max = 320): string {
  const clean = text.replace(/\s+/g, " ").trim();
  if (clean.length <= max) return clean;
  return clean.slice(0, max - 1).trimEnd() + "…";
}

/** "Returns policy - Damaged items (p. 2)" - enough to cite the exact passage. */
export function citationLabel(hit: {
  document_title: string;
  heading_path: string;
  page_from: number | null;
  page_to: number | null;
}): string {
  const parts = [hit.document_title];
  if (hit.heading_path) parts.push(hit.heading_path);
  const page =
    hit.page_from === null
      ? null
      : hit.page_to !== null && hit.page_to !== hit.page_from
        ? `p. ${hit.page_from}-${hit.page_to}`
        : `p. ${hit.page_from}`;
  if (page) parts.push(page);
  return parts.join(" · ");
}

/** Short, human-readable explanation of why this passage was returned. */
export function matchLabel(hit: KnowledgeSearchHit): string[] {
  const labels: string[] = [];
  if (hit.rerank_score !== null) labels.push("Reranked");
  if (hit.similarity !== null)
    labels.push(`Meaning ${Math.round(hit.similarity * 100)}%`);
  if (hit.keyword_rank !== null) labels.push(`Keyword #${hit.keyword_rank}`);
  return labels;
}

/** What the Ask form's Server Action returns (answers are rendered in place). */
export type AskState = {
  attempt: number;
  question: string;
  answer: KnowledgeAnswerResponse | null;
  error: ApiErrorInfo | null;
  fieldError?: string;
};

export type FeedbackState = {
  attempt: number;
  done: boolean;
  helpful: boolean | null;
  error: ApiErrorInfo | null;
};

export const initialFeedbackState: FeedbackState = {
  attempt: 0,
  done: false,
  helpful: null,
  error: null,
};

export const initialAskState: AskState = {
  attempt: 0,
  question: "",
  answer: null,
  error: null,
};

// --- The RERA / price refusal gate (CRM-115 / BP-08, docs/brochures-rera.md) ------------------

/** The backend adds this exact sentence to every answer that names a RERA number. A backend test
 * checks that this copy matches, so the screen can show it as its own note. */
export const LIVE_CHECK_LINE =
  "This is what the cited documents say; it is not a live check of the RERA registry.";

/** The answer without the fixed line, and whether the line was there (only at the very end). */
export function splitLiveCheck(answer: string): {
  text: string;
  liveCheck: boolean;
} {
  if (!answer.endsWith(LIVE_CHECK_LINE))
    return { text: answer, liveCheck: false };
  return {
    text: answer.slice(0, -LIVE_CHECK_LINE.length).trimEnd(),
    liveCheck: true,
  };
}

const REFUSAL_HINTS: Record<string, string> = {
  not_found:
    "Nothing in the knowledge base was close enough; try different words or ask a colleague.",
  ungrounded:
    "The assistant's answer was not fully supported by the documents, so it is not shown.",
  rera_not_found:
    "No document you can see contains that RERA number. Check the number; a live check of the registry is a separate step (Web check on the lead or account page).",
  rera_not_cited:
    "The assistant's answer gave a RERA number that is not in the documents it cited, so it is not shown. Open the brochure itself.",
  price_not_cited:
    "The assistant's answer gave a price that is not in the documents it cited, so it is not shown. Open the brochure itself.",
};

/** Why an answer was refused, in plain words; null for an answer. */
export function refusalHint(reason: string | null | undefined): string | null {
  if (!reason) return null;
  return (
    REFUSAL_HINTS[reason] ??
    "The question could not be answered from the documents."
  );
}
