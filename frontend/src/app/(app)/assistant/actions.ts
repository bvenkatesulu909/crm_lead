"use server";

import type { AssistantProposal } from "@/lib/api-types";
import { apiFetch } from "@/lib/server/api";

import { initialStaffAssistantState, type StaffAssistantState } from "./state";

export async function askStaffAssistant(
  previous: StaffAssistantState,
  formData: FormData,
): Promise<StaffAssistantState> {
  const values = {
    question: String(formData.get("question") ?? "").trim(),
    ticket_id: "",
  };
  const fieldErrors: StaffAssistantState["fieldErrors"] = {};
  if (values.question.length < 3) fieldErrors.question = "Ask a question.";
   if (Object.keys(fieldErrors).length > 0)
    return { ...initialStaffAssistantState, attempt: previous.attempt + 1, values, fieldErrors };
  try {
    const result = await apiFetch<{
      answer: string;
      links: string[];
      proposals?: AssistantProposal[];
    }>("/assistant/ask", {
      method: "POST",
      body: JSON.stringify({ question: values.question }),
    });
    return {
      attempt: previous.attempt + 1,
      answer: result.answer,
      links: result.links,
      proposals: result.proposals ?? [],
      values,
      fieldErrors: {},
      error: null,
    };
  } catch (error) {
    return {
      attempt: previous.attempt + 1,
      answer: null,
      links: [],
      proposals: [],
      values,
      fieldErrors: {},
      error: (await import("@/lib/api-error")).toErrorInfo(error),
    };
  }
}