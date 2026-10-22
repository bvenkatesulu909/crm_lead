"use server";

import { toErrorInfo } from "@/lib/api-error";
import type { KnowledgeAnswerResponse } from "@/lib/api-types";
import type { AskState, FeedbackState } from "@/lib/knowledge";
import { apiFetch } from "@/lib/server/api";

/** Portal Ask box. The backend scopes results to public + granted-account chunks. */
export async function askPortalKnowledge(
  previous: AskState,
  formData: FormData,
): Promise<AskState> {
  const question = String(formData.get("question") ?? "").trim();
  if (!question)
    return {
      attempt: previous.attempt + 1,
      question,
      answer: null,
      error: null,
      fieldError: "Type a question first.",
    };
  if (question.length > 500)
    return {
      attempt: previous.attempt + 1,
      question,
      answer: null,
      error: null,
      fieldError: "At most 500 characters.",
    };
  try {
    const answer = await apiFetch<KnowledgeAnswerResponse>(
      "/portal/knowledge/answer",
      {
        method: "POST",
        body: JSON.stringify({ question }),
        signal: AbortSignal.timeout(60_000),
      },
    );
    return { attempt: previous.attempt + 1, question, answer, error: null };
  } catch (error) {
    return {
      attempt: previous.attempt + 1,
      question,
      answer: null,
      error: toErrorInfo(error),
    };
  }
}

export async function submitPortalFeedback(
  previous: FeedbackState,
  formData: FormData,
): Promise<FeedbackState> {
  const queryId = String(formData.get("query_id") ?? "");
  const helpful = String(formData.get("helpful") ?? "") === "true";
  try {
    await apiFetch("/portal/knowledge/feedback", {
      method: "POST",
      body: JSON.stringify({ query_id: queryId, helpful }),
    });
    return { attempt: previous.attempt + 1, done: true, helpful, error: null };
  } catch (error) {
    return {
      attempt: previous.attempt + 1,
      done: false,
      helpful,
      error: toErrorInfo(error),
    };
  }
}
