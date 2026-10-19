import { z } from "zod";

import { ACTIVITY_KINDS, OPEN_STAGES, PRIORITIES } from "@/lib/api-types";

/**
 * Opportunity and activity form rules - the same limits the backend enforces
 * (sales/schemas.py, activities/schemas.py). The API validates again and has the final word.
 */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const optional = (max: number, label: string) =>
  z
    .string()
    .trim()
    .max(max, `${label} can be at most ${max} characters.`)
    .transform((v) => (v === "" ? null : v));

const id = (message: string) =>
  z
    .string()
    .refine((v) => v === "" || UUID.test(v), message)
    .transform((v) => (v === "" ? null : v));

/** Exact moment with time zone (filled by the browser from a local date/time), or empty. */
const moment = (label: string) =>
  z
    .string()
    .refine(
      (v) =>
        v === "" ||
        (!Number.isNaN(Date.parse(v)) && /[zZ]|[+-]\d\d:?\d\d$/.test(v)),
      `Enter a valid ${label}.`,
    )
    .transform((v) => (v === "" ? null : v));

export const opportunitySchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, "Name is required.")
    .max(255, "Name can be at most 255 characters."),
  account_id: z
    .string()
    .refine((v) => UUID.test(v), "Choose the customer account."),
  primary_contact_id: id("Choose a contact from the list."),
  stage: z.enum(OPEN_STAGES, { message: "Choose a stage." }).optional(),
  amount: z
    .string()
    .trim()
    .refine(
      (v) => v === "" || /^\d{1,16}(\.\d{1,2})?$/.test(v),
      "Enter an amount like 1500 or 1500.50 (no negative values).",
    )
    .transform((v) => (v === "" ? null : v)),
  currency: z
    .string()
    .trim()
    .toUpperCase()
    .refine(
      (v) => /^[A-Z]{3}$/.test(v),
      "Use a 3-letter currency code, e.g. EUR.",
    ),
  expected_close_date: z
    .string()
    .refine(
      (v) => v === "" || /^\d{4}-\d{2}-\d{2}$/.test(v),
      "Enter a valid date.",
    )
    .transform((v) => (v === "" ? null : v)),
  next_step: optional(500, "Next step"),
  description: optional(5000, "Description"),
  owner_id: id("Choose an owner from the list.").optional(),
});
export const OPPORTUNITY_FIELDS = [
  "name",
  "account_id",
  "primary_contact_id",
  "stage",
  "amount",
  "currency",
  "expected_close_date",
  "next_step",
  "description",
  "owner_id",
] as const;

export const activitySchema = z
  .object({
    kind: z.enum(ACTIVITY_KINDS, { message: "Choose a type." }),
    subject: z
      .string()
      .trim()
      .min(1, "Please add a short subject.")
      .max(200, "Subject can be at most 200 characters."),
    body: optional(10_000, "Notes"),
    status: z.enum(["open", "done"]),
    priority: z.enum(PRIORITIES).optional(),
    due_at: moment("due date and time"),
    reminder_at: moment("reminder date and time"),
    occurred_at: moment("date and time"),
    outcome: optional(500, "Outcome"),
    assignee_id: id("Choose who should do it.").optional(),
  })
  .superRefine((a, ctx) => {
    if (a.kind === "note" && a.status === "open")
      ctx.addIssue({ code: "custom", path: ["kind"], message: "A note records something; it can't be a to-do." });
    if (a.status === "open" && a.reminder_at && a.due_at && Date.parse(a.reminder_at) > Date.parse(a.due_at))
      ctx.addIssue({ code: "custom", path: ["reminder_at"], message: "The reminder must be before the due date." });
    if (a.status === "done" && a.occurred_at && Date.parse(a.occurred_at) > Date.now() + 5 * 60_000)
      ctx.addIssue({ code: "custom", path: ["occurred_at"], message: "Something that happened can't be in the future." });
  }); // prettier-ignore

/** Only the fields that make sense for open items vs. logged (done) ones are sent. */
export function activityPayload(a: z.infer<typeof activitySchema>) {
  const common = {
    kind: a.kind,
    subject: a.subject,
    body: a.body,
    ...(a.assignee_id ? { assignee_id: a.assignee_id } : {}),
  };
  return a.status === "open"
    ? {
        ...common,
        status: "open" as const,
        priority: a.priority ?? "normal",
        due_at: a.due_at,
        reminder_at: a.reminder_at,
      }
    : {
        ...common,
        status: "done" as const,
        ...(a.occurred_at ? { occurred_at: a.occurred_at } : {}),
        outcome: a.outcome,
      };
}

export function errorsOf(error: z.ZodError): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const issue of error.issues)
    errors[String(issue.path[0])] ??= issue.message;
  return errors;
}
