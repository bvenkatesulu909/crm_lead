import type { ApiErrorInfo } from "@/lib/api-error";
import type { AssistantProposal } from "@/lib/api-types";

export type StaffAssistantState = {
  attempt: number;
  answer: string | null;
  links: string[];
  /** Changes the assistant proposed; they wait for a manager's approval. */
  proposals: AssistantProposal[];
  values: { question: string; ticket_id: string };
  fieldErrors: Partial<Record<"question" | "ticket_id", string>>;
  error: ApiErrorInfo | null;
};

export const initialStaffAssistantState: StaffAssistantState = {
  attempt: 0,
  answer: null,
  links: [],
  proposals: [],
  values: { question: "", ticket_id: "" },
  fieldErrors: {},
  error: null,
};
