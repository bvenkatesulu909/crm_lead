"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { Ticket } from "@/lib/api-types";
import type { DialogState } from "@/lib/dialog-state";
import type { FormState } from "@/lib/form-state";
import { apiFetch } from "@/lib/server/api";
import {
  errorsOf,
  staffCommentSchema,
  staffTicketSchema,
} from "@/lib/validation/tickets";

/**
 * Staff ticket Server Actions. IDs and versions come from the browser and are untrusted; the
 * API decides whether this user may change this ticket. No permission logic here.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ticketPath = (id: string) => {
  if (!UUID.test(id)) throw new Error("invalid ticket id");
  return `/tickets/${id}`;
};
const STATUSES = new Set(["open", "pending_customer", "resolved", "closed"]);

const text = (formData: FormData, name: string) =>
  String(formData.get(name) ?? "");

export async function createTicket(
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const values = {
    account_id: text(formData, "account_id"),
    priority: text(formData, "priority"),
    category: text(formData, "category") || "question",
    subject: text(formData, "subject"),
    description: text(formData, "description"),
  };
  const attempt = previous.attempt + 1;
  const parsed = staffTicketSchema.safeParse(values);
  if (!parsed.success)
    return {
      attempt,
      values,
      fieldErrors: errorsOf(parsed.error),
      error: null,
    };
  let ticket: Ticket;
  try {
    ticket = await apiFetch<Ticket>("/tickets", {
      method: "POST",
      body: JSON.stringify(parsed.data),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return { attempt, values, fieldErrors: info.fieldErrors, error: info };
  }
  redirect(`/tickets/${ticket.id}?done=created`);
}

export async function addStaffComment(
  ticketId: string,
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const path = ticketPath(ticketId);
  const values = {
    body: text(formData, "body"),
    visibility: text(formData, "visibility") || "public",
  };
  const attempt = previous.attempt + 1;
  const parsed = staffCommentSchema.safeParse(values);
  if (!parsed.success)
    return {
      attempt,
      values,
      fieldErrors: errorsOf(parsed.error),
      error: null,
    };
  try {
    await apiFetch(`${path}/comments`, {
      method: "POST",
      body: JSON.stringify(parsed.data),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return { attempt, values, fieldErrors: info.fieldErrors, error: info };
  }
  redirect(
    `${path}?done=${parsed.data.visibility === "internal" ? "noted" : "replied"}`,
  );
}

const failed = (previous: DialogState, error: unknown): DialogState => {
  const info = toErrorInfo(error);
  return {
    attempt: previous.attempt + 1,
    fieldErrors: info.fieldErrors,
    error: info,
  };
};

export async function changeTicketStatus(
  ticketId: string,
  target: string,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const path = ticketPath(ticketId);
  if (!STATUSES.has(target)) throw new Error("invalid status");
  const reason = text(formData, "reason").trim();
  if (reason.length > 500) {
    return {
      attempt: previous.attempt + 1,
      fieldErrors: { reason: "Reason can be at most 500 characters." },
      error: null,
    };
  }
  try {
    await apiFetch(`${path}/status`, {
      method: "POST",
      body: JSON.stringify({ status: target, reason: reason || null }),
    });
  } catch (error) {
    return failed(previous, error);
  }
  redirect(`${path}?done=status`);
}

export async function assignTicket(
  ticketId: string,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const path = ticketPath(ticketId);
  const assignee = text(formData, "assignee_id");
  if (!UUID.test(assignee)) {
    return {
      attempt: previous.attempt + 1,
      fieldErrors: { assignee_id: "Choose who should handle this ticket." },
      error: null,
    };
  }
  try {
    await apiFetch(`${path}/assign`, {
      method: "POST",
      body: JSON.stringify({ assignee_id: assignee }),
    });
  } catch (error) {
    return failed(previous, error);
  }
  redirect(`${path}?done=assigned`);
}

export async function changePriority(
  ticketId: string,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const path = ticketPath(ticketId);
  const priority = text(formData, "priority");
  if (!["low", "normal", "high", "urgent"].includes(priority)) {
    return {
      attempt: previous.attempt + 1,
      fieldErrors: { priority: "Choose a priority." },
      error: null,
    };
  }
  try {
    await apiFetch(path, {
      method: "PATCH",
      body: JSON.stringify({
        version: Number(text(formData, "version")),
        priority,
        ...([
          "question",
          "problem",
          "request",
          "complaint",
          "feedback",
        ].includes(text(formData, "category"))
          ? { category: text(formData, "category") }
          : {}),
      }),
    });
  } catch (error) {
    return failed(previous, error);
  }
  redirect(`${path}?done=priority`);
}
