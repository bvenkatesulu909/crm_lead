import type { ApiErrorInfo } from "@/lib/api-error";

export type StaffAssistantState = {
  attempt: number;
  answer: string | null;
  links: string[];
  values: { question: string; ticket_id: string };
  fieldErrors: Partial<Record<"question" | "ticket_id", string>>;
  error: ApiErrorInfo | null;
};

export const initialStaffAssistantState: StaffAssistantState = {
  attempt: 0,
  answer: null,
  links: [],
  values: { question: "", ticket_id: "" },
  fieldErrors: {},
  error: null,
};
