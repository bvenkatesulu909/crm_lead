"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { PortalTicket } from "@/lib/api-types";
import type { FormState } from "@/lib/form-state";
import { apiFetch } from "@/lib/server/api";
import {
  commentSchema,
  errorsOf,
  portalTicketSchema,
  ratingSchema,
} from "@/lib/validation/tickets";

/**
 * Customer-portal Server Actions. The account ID comes from the browser: the API accepts it
 * only if it is one of THIS customer's granted accounts (otherwise 404).
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const text = (formData: FormData, name: string) =>
  String(formData.get(name) ?? "");

export async function openTicket(
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const values = {
    account_id: text(formData, "account_id"),
    category: text(formData, "category") || "question",
    subject: text(formData, "subject"),
    description: text(formData, "description"),
  };
  const attempt = previous.attempt + 1;
  const parsed = portalTicketSchema.safeParse(values);
  if (!parsed.success)
    return {
      attempt,
      values,
      fieldErrors: errorsOf(parsed.error),
      error: null,
    };
  let ticket: PortalTicket;
  try {
    ticket = await apiFetch<PortalTicket>("/portal/tickets", {
      method: "POST",
      body: JSON.stringify(parsed.data),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return { attempt, values, fieldErrors: info.fieldErrors, error: info };
  }
  redirect(`/portal/tickets/${ticket.id}?done=created`);
}

export async function replyToTicket(
  ticketId: string,
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  if (!UUID.test(ticketId)) throw new Error("invalid ticket id");
  const values = { body: text(formData, "body") };
  const attempt = previous.attempt + 1;
  const parsed = commentSchema.safeParse(values);
  if (!parsed.success)
    return {
      attempt,
      values,
      fieldErrors: errorsOf(parsed.error),
      error: null,
    };
  try {
    await apiFetch(`/portal/tickets/${ticketId}/comments`, {
      method: "POST",
      body: JSON.stringify(parsed.data),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return { attempt, values, fieldErrors: info.fieldErrors, error: info };
  }
  redirect(`/portal/tickets/${ticketId}?done=replied`);
}

export async function rateTicket(
  ticketId: string,
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  if (!UUID.test(ticketId)) throw new Error("invalid ticket id");
  const values = {
    rating: text(formData, "rating"),
    comment: text(formData, "comment"),
  };
  const attempt = previous.attempt + 1;
  const parsed = ratingSchema.safeParse(values);
  if (!parsed.success)
    return {
      attempt,
      values,
      fieldErrors: errorsOf(parsed.error),
      error: null,
    };
  try {
    await apiFetch(`/portal/tickets/${ticketId}/rating`, {
      method: "POST",
      body: JSON.stringify(parsed.data),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return { attempt, values, fieldErrors: info.fieldErrors, error: info };
  }
  redirect(`/portal/tickets/${ticketId}?done=rated`);
}
