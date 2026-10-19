import { z } from "zod";

/**
 * Quote form rules - the same limits as backend/app/modules/quotes/schemas.py. Prices are
 * NOT part of the form: the API takes them from the price book.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const optionalId = (message: string) =>
  z
    .string()
    .refine((v) => v === "" || UUID.test(v), message)
    .transform((v) => (v === "" ? null : v));

export const quoteLineSchema = z.object({
  product_id: z.string().refine((v) => UUID.test(v), "Choose a product."),
  quantity: z
    .string()
    .trim()
    .refine(
      (v) => /^\d{1,7}(\.\d{1,3})?$/.test(v) && Number(v) > 0,
      "Quantity must be more than 0 (up to 3 decimals).",
    ),
  discount_percent: z
    .string()
    .trim()
    .transform((v) => (v === "" ? "0" : v))
    .refine(
      (v) => /^\d{1,3}(\.\d{1,2})?$/.test(v) && Number(v) <= 100,
      "Discount must be between 0 and 100 %.",
    ),
});

export const quoteSchema = z.object({
  account_id: z
    .string()
    .refine((v) => UUID.test(v), "Choose the customer account."),
  title: z
    .string()
    .trim()
    .min(1, "Give the quote a title.")
    .max(200, "Title can be at most 200 characters."),
  price_book_id: z.string().refine((v) => UUID.test(v), "Choose a price book."),
  opportunity_id: optionalId("Choose a deal from the list."),
  contact_id: optionalId("Choose a contact from the list."),
  valid_until: z
    .string()
    .refine(
      (v) => /^\d{4}-\d{2}-\d{2}$/.test(v),
      "Choose until when the quote is valid.",
    ),
  customer_note: z
    .string()
    .trim()
    .max(5000, "The note can be at most 5,000 characters.")
    .transform((v) => (v === "" ? null : v)),
  internal_note: z
    .string()
    .trim()
    .max(5000, "The note can be at most 5,000 characters.")
    .transform((v) => (v === "" ? null : v)),
  lines: z
    .array(quoteLineSchema)
    .max(100, "A quote can have at most 100 lines."),
});

export type QuoteInput = z.infer<typeof quoteSchema>;

/** Field errors, with line errors reported as "lines" (one message for the line table). */
export function quoteErrors(error: z.ZodError): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const issue of error.issues) {
    const key = String(issue.path[0]);
    const message =
      key === "lines" && typeof issue.path[1] === "number"
        ? `Line ${issue.path[1] + 1}: ${issue.message}`
        : issue.message;
    errors[key] ??= message;
  }
  return errors;
}
