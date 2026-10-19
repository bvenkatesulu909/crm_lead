import { z } from "zod";

import { TICKET_CATEGORIES, TICKET_PRIORITIES } from "@/lib/api-types";

/** Ticket input rules - the same limits as backend/app/modules/support/schemas.py. */

const subject = z
  .string()
  .trim()
  .min(3, "Please give a short subject (at least 3 characters).")
  .max(200, "Subject can be at most 200 characters.");
const longText = (what: string) =>
  z
    .string()
    .trim()
    .min(1, `${what} is required.`)
    .max(10_000, `${what} can be at most 10,000 characters.`);

export const portalTicketSchema = z.object({
  account_id: z.uuid({ message: "Choose the account this is about." }),
  subject,
  description: longText("Description"),
  category: z.enum(TICKET_CATEGORIES, {
    message: "Choose what this is about.",
  }),
});

export const ratingSchema = z.object({
  rating: z.coerce
    .number()
    .int()
    .min(1, "Choose 1 to 5 stars.")
    .max(5, "Choose 1 to 5 stars."),
  comment: z
    .string()
    .trim()
    .max(1000, "Comment can be at most 1,000 characters.")
    .transform((v) => (v === "" ? null : v)),
});

export const staffTicketSchema = portalTicketSchema.extend({
  priority: z.enum(TICKET_PRIORITIES, { message: "Choose a priority." }),
});

export const commentSchema = z.object({ body: longText("Message") });

export const staffCommentSchema = commentSchema.extend({
  visibility: z.enum(["public", "internal"]),
});

export function errorsOf(error: z.ZodError): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const issue of error.issues)
    errors[String(issue.path[0])] ??= issue.message;
  return errors;
}
