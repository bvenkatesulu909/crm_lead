import type { ApiErrorInfo } from "@/lib/api-error";

/** What a dialog's Server Action returns when it did NOT succeed (success redirects). */
export type DialogState = {
  attempt: number;
  fieldErrors: Record<string, string>;
  error: ApiErrorInfo | null;
};

export const initialDialogState: DialogState = {
  attempt: 0,
  fieldErrors: {},
  error: null,
};
