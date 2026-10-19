import type { ApiErrorInfo } from "@/lib/api-error";
import type { FieldErrors, LeadField } from "@/lib/validation/lead";

/** What a lead-form Server Action (create or edit) returns to the form after a failed attempt. */
export type LeadFormState = {
  attempt: number;
  values: Partial<Record<LeadField, string>>;
  fieldErrors: FieldErrors;
  error: ApiErrorInfo | null;
};

export const initialLeadFormState: LeadFormState = {
  attempt: 0,
  values: {},
  fieldErrors: {},
  error: null,
};
