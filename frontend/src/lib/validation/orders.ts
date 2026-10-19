import { z } from "zod";

/** Order input rules - the same limits as backend/app/modules/orders/schemas.py. */

const decimal = (places: number, what: string, example: string) =>
  z
    .string()
    .trim()
    .regex(
      new RegExp(`^\\d{1,13}(\\.\\d{1,${places}})?$`),
      `${what}: use a number with at most ${places} decimals, e.g. ${example}.`,
    );

export const orderLineSchema = z.object({
  product_code: z
    .string()
    .trim()
    .max(64, "Product code can be at most 64 characters.")
    .transform((v) => v || null),
  description: z
    .string()
    .trim()
    .min(1, "Describe what is ordered.")
    .max(500, "Description can be at most 500 characters."),
  quantity: decimal(3, "Quantity", "1.5").refine(
    (v) => Number(v) > 0 && Number(v) <= 1_000_000,
    "Quantity must be more than 0 and at most 1,000,000.",
  ),
  unit_price: decimal(2, "Unit price", "19.99").refine(
    (v) => Number(v) <= 1_000_000_000,
    "Unit price can be at most 1,000,000,000.",
  ),
  tax_rate: decimal(2, "Tax rate", "19").refine(
    (v) => Number(v) <= 100,
    "Tax rate must be between 0 and 100 %.",
  ),
});
export type OrderLineInput = z.output<typeof orderLineSchema>;

const optional = (max: number, what: string) =>
  z
    .string()
    .trim()
    .max(max, `${what} can be at most ${max} characters.`)
    .transform((v) => v || null);

export const orderHeaderSchema = z.object({
  currency: z.string().regex(/^[A-Z]{3}$/, "Choose a currency."),
  customer_reference: optional(100, "Customer reference"),
  expected_delivery_date: z
    .string()
    .trim()
    .regex(/^(\d{4}-\d{2}-\d{2})?$/, "Use a valid date.")
    .transform((v) => v || null),
  internal_note: optional(2000, "Internal note"),
});

export const CURRENCIES = ["EUR", "USD", "GBP", "CHF"] as const;
export const MAX_LINES = 100;
