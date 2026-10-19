import { z } from "zod";

/**
 * Product and price book rules - the same limits as backend/app/modules/catalog/schemas.py.
 * Checking them here gives quick feedback; the API checks everything again.
 */
export const PRODUCT_TYPES = ["product", "service", "subscription"] as const;

const percent = z
  .string()
  .trim()
  .transform((v) => (v === "" ? "0" : v.replace(",", ".")))
  .refine(
    (v) => /^\d{1,3}(\.\d{1,2})?$/.test(v) && Number(v) <= 100,
    "Tax rate must be between 0 and 100 % (up to 2 decimals).",
  );

const optionalText = (max: number) =>
  z
    .string()
    .trim()
    .max(
      max,
      `This text can be at most ${max.toLocaleString("en")} characters.`,
    )
    .transform((v) => (v === "" ? null : v));

export const productSchema = z.object({
  sku: z
    .string()
    .trim()
    .min(1, "Enter a product code (SKU).")
    .max(64, "The product code can be at most 64 characters.")
    .regex(
      /^[A-Za-z0-9._-]+$/,
      "Use only letters, digits, dot, dash and underscore.",
    ),
  name: z
    .string()
    .trim()
    .min(1, "Enter the product name.")
    .max(200, "The name can be at most 200 characters."),
  description: optionalText(5000),
  product_type: z.enum(PRODUCT_TYPES, "Choose a product type."),
  unit: z
    .string()
    .trim()
    .min(1, "Enter a unit, e.g. each or hour.")
    .max(20, "The unit can be at most 20 characters."),
  tax_rate: percent,
});
export type ProductInput = z.infer<typeof productSchema>;

export const priceBookSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, "Give the price book a name.")
    .max(100, "The name can be at most 100 characters."),
  currency: z
    .string()
    .trim()
    .toUpperCase()
    .regex(/^[A-Z]{3}$/, "Use a 3-letter currency code, e.g. EUR."),
  description: optionalText(500),
  is_default: z.boolean(),
});

export const priceSchema = z.object({
  unit_price: z
    .string()
    .trim()
    .transform((v) => v.replace(",", "."))
    .refine(
      (v) => /^\d{1,10}(\.\d{1,2})?$/.test(v) && Number(v) <= 1_000_000_000,
      "Enter a price of 0 or more with up to 2 decimals.",
    ),
});

/** First error message per field. */
export function fieldErrors(error: z.ZodError): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const issue of error.issues)
    errors[String(issue.path[0])] ??= issue.message;
  return errors;
}
