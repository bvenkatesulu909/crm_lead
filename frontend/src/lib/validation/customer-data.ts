import { z } from "zod";

import {
  ACCOUNT_TYPES,
  CHANNELS,
  EMAIL_CONSENTS,
  LIFECYCLE_STAGES,
  SEGMENTS,
} from "@/lib/api-types";

/**
 * Account and contact form rules - the same limits the backend enforces
 * (backend/app/core/validation.py, accounts/schemas.py, contacts/schemas.py). Checked in the
 * Server Action before calling the API; the API validates again and has the final word.
 *
 * Empty optional fields become `null`, which on an edit means "clear this field". On create,
 * nulls are dropped so the API applies its defaults.
 */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const optional = (max: number, label: string) =>
  z
    .string()
    .trim()
    .max(max, `${label} can be at most ${max} characters.`)
    .transform((v) => (v === "" ? null : v));

const phone = (label: string) =>
  optional(50, label).refine(
    (v) => v === null || /^[0-9+().\-\s]{3,50}$/.test(v),
    `${label} may contain only digits, spaces and + ( ) . -`,
  );

const email = optional(320, "E-mail").refine(
  (v) => v === null || /^[^@\s]{1,64}@[^@\s]+\.[^@\s]+$/.test(v),
  "Enter a valid e-mail address, like name@example.com.",
);

const website = optional(2048, "Website").refine(
  (v) =>
    v === null ||
    /^https?:\/\/[^\s/]+\.[^\s]+$/i.test(v) ||
    // Without a scheme the API adds https:// - but "javascript:..." and friends are refused.
    (!/^[a-z][a-z0-9+.-]*:(?!\d)/i.test(v) && /^[^\s/]+\.[^\s]+$/.test(v)),
  "Enter a web address such as https://example.com.",
);

const choice = <T extends readonly [string, ...string[]]>(values: T) =>
  z
    .union([z.enum(values), z.literal("")])
    .transform((v) => (v === "" ? null : v));

const id = (message: string) =>
  z
    .string()
    .refine((v) => v === "" || UUID.test(v), message)
    .transform((v) => (v === "" ? null : v));

const code = (pattern: RegExp, message: string, upper: boolean) =>
  z
    .string()
    .trim()
    .transform((v) => (upper ? v.toUpperCase() : v.toLowerCase()))
    .refine((v) => v === "" || pattern.test(v), message)
    .transform((v) => (v === "" ? null : v));
const country = code(
  /^[A-Z]{2}$/,
  "Use a 2-letter country code, e.g. IN or DE.",
  true,
);
const language = code(
  /^[a-z]{2}$/,
  "Use a 2-letter language code, e.g. en or hi.",
  false,
);

const checkbox = z
  .union([z.literal("on"), z.literal("")])
  .transform((v) => v === "on");

export const accountSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, "Name is required.")
    .max(255, "Name can be at most 255 characters."),
  account_number: optional(50, "Account number"),
  website,
  industry: optional(100, "Industry"),
  phone: phone("Phone"),
  segment: choice(SEGMENTS),
  preferred_channel: choice(CHANNELS),
  country,
  region: optional(100, "Region"),
  city: optional(100, "City"),
  lifecycle_stage: choice(LIFECYCLE_STAGES),
  account_type: z.enum(ACCOUNT_TYPES, { message: "Choose an account type." }),
  preferred_language: language,
  parent_account_id: id("Choose a parent account from the list."),
  owner_id: id("Choose an owner from the list.").optional(),
});
export type AccountInput = z.infer<typeof accountSchema>;
export const ACCOUNT_FIELDS = [
  "name",
  "account_number",
  "website",
  "industry",
  "phone",
  "segment",
  "preferred_channel",
  "country",
  "region",
  "city",
  "lifecycle_stage",
  "account_type",
  "preferred_language",
  "parent_account_id",
  // Display only: the parent's name, so the form can show it again after an error.
  "parent_account_label",
  "owner_id",
] as const;

export const contactSchema = z
  .object({
    first_name: optional(100, "First name"),
    last_name: z
      .string()
      .trim()
      .min(1, "Last name is required.")
      .max(100, "Last name can be at most 100 characters."),
    email,
    phone: phone("Phone"),
    mobile: phone("Mobile"),
    job_title: optional(150, "Designation"),
    department: optional(100, "Department"),
    account_id: id("Choose an account from the list."),
    is_primary: checkbox,
    preferred_channel: choice(CHANNELS),
    email_consent: z.enum(EMAIL_CONSENTS, {
      message: "Choose the e-mail consent.",
    }),
    do_not_call: checkbox,
    preferred_language: language,
    owner_id: id("Choose an owner from the list.").optional(),
  })
  .refine((c) => !c.is_primary || c.account_id !== null, {
    path: ["is_primary"],
    message: "Only a contact linked to an account can be its primary contact.",
  });
export type ContactInput = z.infer<typeof contactSchema>;
export const CONTACT_FIELDS = [
  "first_name",
  "last_name",
  "email",
  "phone",
  "mobile",
  "job_title",
  "department",
  "account_id",
  // Display only: the account's name, so the form can show it again after an error.
  "account_label",
  "is_primary",
  "preferred_channel",
  "email_consent",
  "do_not_call",
  "preferred_language",
  "owner_id",
] as const;

/**
 * Raw form values. Fields missing from the form (e.g. "owner" for users who may not change
 * it) are left out, so they are never sent to the API.
 */
export function readForm(
  formData: FormData,
  fields: readonly string[],
): Record<string, string> {
  const values: Record<string, string> = {};
  for (const field of fields) {
    const value = formData.get(field);
    if (value !== null) values[field] = String(value);
  }
  return values;
}

/** For checkbox fields: an unchecked box is absent from FormData but means "false". */
export function withCheckboxes(
  values: Record<string, string>,
  formData: FormData,
  boxes: readonly string[],
): Record<string, string> {
  const result = { ...values };
  for (const box of boxes)
    if (formData.get(`${box}__present`) !== null) result[box] ??= "";
  return result;
}

/** Create requests leave out empty optional fields so the API applies its defaults. */
export function withoutNulls<T extends Record<string, unknown>>(data: T) {
  return Object.fromEntries(
    Object.entries(data).filter(([, v]) => v !== null && v !== undefined),
  ) as Partial<T>;
}

export function errorsOf(error: z.ZodError): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const issue of error.issues)
    errors[String(issue.path[0])] ??= issue.message;
  return errors;
}
