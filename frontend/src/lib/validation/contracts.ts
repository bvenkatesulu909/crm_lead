import { z } from "zod";

import { BILLING_FREQUENCIES } from "@/lib/api-types";

/**
 * Contract form rules - the same limits as backend/app/modules/contracts/schemas.py. The API
 * checks everything again (the server never trusts the browser).
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DATE = /^\d{4}-\d{2}-\d{2}$/;

const optionalDate = (message: string) =>
  z
    .string()
    .trim()
    .refine((v) => v === "" || DATE.test(v), message)
    .transform((v) => (v === "" ? null : v));

const optionalText = (max: number, message: string) =>
  z
    .string()
    .trim()
    .max(max, message)
    .transform((v) => (v === "" ? null : v));

const fields = {
  title: z
    .string()
    .trim()
    .min(1, "Give the contract a title.")
    .max(200, "Title can be at most 200 characters."),
  start_date: optionalDate("Enter the start date."),
  end_date: optionalDate("Enter the end date."),
  total_value: z
    .string()
    .trim()
    .transform((v) => v.replace(",", "."))
    .refine(
      (v) => /^\d{1,14}(\.\d{1,2})?$/.test(v),
      "Enter an amount such as 12000.50 (up to 2 decimals).",
    ),
  currency: z
    .string()
    .trim()
    .transform((v) => v.toUpperCase())
    .refine(
      (v) => /^[A-Z]{3}$/.test(v),
      "Use a 3-letter currency code, e.g. EUR.",
    ),
  billing_frequency: z.enum(BILLING_FREQUENCIES, {
    message: "Choose how often it is billed.",
  }),
  auto_renew: z.string().transform((v) => v === "on" || v === "true"),
  renewal_notice_days: z
    .string()
    .trim()
    .refine(
      (v) => /^\d{1,3}$/.test(v) && Number(v) <= 365,
      "Notice can be 0 to 365 days.",
    )
    .transform(Number),
  renewal_term_months: z
    .string()
    .trim()
    .refine(
      (v) =>
        v === "" || (/^\d{1,3}$/.test(v) && Number(v) >= 1 && Number(v) <= 120),
      "The renewal term can be 1 to 120 months.",
    )
    .transform((v) => (v === "" ? null : Number(v))),
  terms: optionalText(10000, "The terms can be at most 10,000 characters."),
};

const datesInOrder = (d: {
  start_date: string | null;
  end_date: string | null;
}) => !d.start_date || !d.end_date || d.end_date >= d.start_date;
const ORDER_ERROR = {
  message: "The end date cannot be before the start date.",
  path: ["end_date"],
};

/** A new contract (draft). */
export const contractSchema = z
  .object({
    account_id: z
      .string()
      .refine((v) => UUID.test(v), "Choose the customer account."),
    ...fields,
  })
  .refine(datesInOrder, ORDER_ERROR);

/** What an ACTIVE contract may still change (everything else changes by renewing). */
export const activeContractSchema = z.object({
  title: fields.title,
  auto_renew: fields.auto_renew,
  renewal_notice_days: fields.renewal_notice_days,
  renewal_term_months: fields.renewal_term_months,
  terms: fields.terms,
});

/** Editing a draft: every business field except the account. */
export const draftContractSchema = z
  .object(fields)
  .refine(datesInOrder, ORDER_ERROR);

export type ContractInput = z.infer<typeof contractSchema>;

/** Field errors keyed by field name (first message per field). */
export function contractErrors(error: z.ZodError): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const issue of error.issues)
    errors[String(issue.path[0])] ??= issue.message;
  return errors;
}
