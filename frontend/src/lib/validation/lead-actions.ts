import { z } from "zod";

/** Input rules for the lead dialogs - same limits as the backend's request schemas. */

const reason = z
  .string()
  .trim()
  .max(500, "Reason can be at most 500 characters.")
  .transform((v) => (v === "" ? undefined : v))
  .optional();

const uuid = (message: string) => z.uuid({ message });

export const assignSchema = z.object({
  owner_id: uuid("Choose who should own this lead."),
  reason,
});

export const qualifySchema = z.object({ reason });

export const disqualifySchema = z.object({
  reason: z
    .string()
    .trim()
    .min(1, "Please say why this lead is not a fit.")
    .max(500, "Reason can be at most 500 characters."),
});

export const convertSchema = z
  .object({
    account_mode: z.enum(["new", "existing"]),
    account_name: z
      .string()
      .trim()
      .max(255, "Account name can be at most 255 characters.")
      .transform((v) => (v === "" ? undefined : v))
      .optional(),
    existing_account_id: z.string().optional(),
    create_opportunity: z.boolean(),
    opportunity_name: z
      .string()
      .trim()
      .max(255, "Opportunity name can be at most 255 characters.")
      .transform((v) => (v === "" ? undefined : v))
      .optional(),
    amount: z
      .string()
      .trim()
      .refine(
        (v) => v === "" || /^\d{1,16}(\.\d{1,2})?$/.test(v),
        "Enter an amount like 1250 or 1250.50.",
      )
      .transform((v) => (v === "" ? undefined : v))
      .optional(),
    currency: z.string().trim().toUpperCase().optional(),
    expected_close_date: z
      .string()
      .refine(
        (v) => v === "" || /^\d{4}-\d{2}-\d{2}$/.test(v),
        "Use the date picker.",
      )
      .transform((v) => (v === "" ? undefined : v))
      .optional(),
  })
  .superRefine((data, ctx) => {
    if (
      data.account_mode === "existing" &&
      !z.uuid().safeParse(data.existing_account_id).success
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["existing_account_id"],
        message: "Choose an account.",
      });
    }
    if (data.create_opportunity && !/^[A-Z]{3}$/.test(data.currency ?? "")) {
      ctx.addIssue({
        code: "custom",
        path: ["currency"],
        message: "Use a 3-letter currency code, e.g. EUR.",
      });
    }
  });

/** The backend's request body for POST /leads/{id}/convert. */
export function convertPayload(data: z.infer<typeof convertSchema>) {
  return {
    account:
      data.account_mode === "existing"
        ? { existing_account_id: data.existing_account_id }
        : { name: data.account_name ?? null },
    opportunity: data.create_opportunity
      ? {
          name: data.opportunity_name ?? null,
          amount: data.amount ?? null,
          currency: data.currency,
          expected_close_date: data.expected_close_date ?? null,
        }
      : null,
  };
}

export function fieldErrorsOf(error: z.ZodError): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const issue of error.issues)
    errors[String(issue.path[0])] ??= issue.message;
  return errors;
}
