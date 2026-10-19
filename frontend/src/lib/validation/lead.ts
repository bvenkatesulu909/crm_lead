import { z } from "zod";

import { LEAD_SOURCES } from "@/lib/api-types";

/**
 * Create-lead form rules - the same limits the backend enforces (backend/app/modules/leads/
 * schemas.py). Used in the browser for instant feedback AND on the server before calling the
 * API. The backend still validates again: it never trusts this app.
 */
const optionalText = (max: number, label: string) =>
  z
    .string()
    .trim()
    .max(max, `${label} can be at most ${max} characters.`)
    .transform((v) => (v === "" ? undefined : v))
    .optional();

export const leadCreateSchema = z.object({
  first_name: optionalText(100, "First name"),
  last_name: z
    .string()
    .trim()
    .min(1, "Last name is required.")
    .max(100, "Last name can be at most 100 characters."),
  company_name: optionalText(255, "Company"),
  email: optionalText(320, "E-mail").refine(
    (v) => v === undefined || /^[^@\s]{1,64}@[^@\s]+\.[^@\s]+$/.test(v),
    "Enter a valid e-mail address, like name@example.com.",
  ),
  phone: optionalText(50, "Phone").refine(
    (v) => v === undefined || /^[0-9+().\-\s]{3,50}$/.test(v),
    "Phone may contain only digits, spaces and + ( ) . -",
  ),
  job_title: optionalText(150, "Job title"),
  source: z
    .union([z.enum(LEAD_SOURCES), z.literal("")])
    .transform((v) => (v === "" ? undefined : v))
    .optional(),
});

export type LeadCreateInput = z.infer<typeof leadCreateSchema>;
export const LEAD_FIELDS = [
  "first_name",
  "last_name",
  "company_name",
  "email",
  "phone",
  "job_title",
  "source",
] as const;
export type LeadField = (typeof LEAD_FIELDS)[number];

export type FieldErrors = Partial<Record<LeadField, string>>;

/** Validates raw form values; returns either clean data or one message per field. */
export function validateLead(
  values: Record<string, unknown>,
): { ok: true; data: LeadCreateInput } | { ok: false; errors: FieldErrors } {
  const result = leadCreateSchema.safeParse(values);
  if (result.success) return { ok: true, data: result.data };
  const errors: FieldErrors = {};
  for (const issue of result.error.issues) {
    const field = issue.path[0] as LeadField;
    errors[field] ??= issue.message;
  }
  return { ok: false, errors };
}

export function formValues(formData: FormData): Record<LeadField, string> {
  return Object.fromEntries(
    LEAD_FIELDS.map((field) => [field, String(formData.get(field) ?? "")]),
  ) as Record<LeadField, string>;
}
