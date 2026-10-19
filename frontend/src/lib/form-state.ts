import type { ApiErrorInfo } from "@/lib/api-error";

/** "Did you mean…?" - possible duplicates found before creating a record. */
export type DuplicateNotice = {
  items: { label: string; href: string; detail: string }[];
  /** Matches the user may not see (only counted, never named). */
  hidden: number;
};

/** What a form's Server Action returns after a failed attempt (success redirects). */
export type FormState = {
  attempt: number;
  values: Record<string, string>;
  fieldErrors: Record<string, string>;
  error: ApiErrorInfo | null;
  /** Set when the record looks like an existing one; the user must confirm to continue. */
  duplicates?: DuplicateNotice | null;
};

export const initialFormState: FormState = {
  attempt: 0,
  values: {},
  fieldErrors: {},
  error: null,
};
