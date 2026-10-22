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
