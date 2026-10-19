import { z } from "zod";

import { PAYMENT_METHODS } from "@/lib/api-types";

/** Invoice input rules - the same limits as backend/app/modules/invoices/schemas.py. */

const amount = (what: string) =>
  z
    .string()
    .trim()
    .regex(
      /^\d{1,10}(\.\d{1,2})?$/,
      `${what}: use a number with at most 2 decimals, e.g. 19.99.`,
    )
    .refine((v) => Number(v) > 0, `${what} must be more than 0.`);

const isoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "Choose a date.");

const reason = (what: string) =>
  z
    .string()
    .trim()
    .min(3, `${what} (at least 3 characters).`)
    .max(500, "At most 500 characters.");

export const paymentSchema = z.object({
  amount: amount("Amount"),
  received_on: isoDate,
  method: z.enum(PAYMENT_METHODS, { message: "Choose how it was paid." }),
  reference: z
    .string()
    .trim()
    .max(100, "Reference can be at most 100 characters.")
    .transform((v) => v || null),
});

export const reversalSchema = z.object({
  reason: reason("Say why the payment is reversed"),
});

export const creditNoteSchema = z.object({
  reason: reason("Tell the customer why"),
  description: z
    .string()
    .trim()
    .min(1, "Describe what is credited.")
    .max(500, "At most 500 characters."),
  unit_price: amount("Net amount"),
  tax_rate: z
    .string()
    .trim()
    .regex(/^\d{1,3}(\.\d{1,2})?$/, "Tax rate: a number such as 19.")
    .refine((v) => Number(v) <= 100, "Tax rate must be between 0 and 100 %."),
});

export const issueSchema = z.object({ due_date: isoDate });
