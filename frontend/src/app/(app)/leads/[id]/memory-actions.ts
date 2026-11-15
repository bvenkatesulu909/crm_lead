"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import {
  checkConfirm,
  checkNewMemory,
  memoryErrorText,
} from "@/lib/buyer-memory";
import type { DialogState } from "@/lib/dialog-state";
import { leadPath } from "@/lib/qualifier";
import { apiFetch } from "@/lib/server/api";

/**
 * Buyer memory Server Actions (ADR 0028). The lead id comes from the page and is checked here; the
 * API decides who may read and write the lead and applies every rule again. What is sent is built
 * from a short list of fields: a fact is always "the buyer confirmed" with its quote, and nothing
 * else in the form (a tenant, a lead, a source) is ever passed on.
 */

const text = (formData: FormData, name: string) =>
  String(formData.get(name) ?? "");

function failure(previous: DialogState, error: unknown): DialogState {
  const info = toErrorInfo(error);
  return {
    attempt: previous.attempt + 1,
    fieldErrors: info.fieldErrors,
    error: { ...info, message: memoryErrorText(info.code, info.message) },
  };
}

function invalid(
  previous: DialogState,
  fieldErrors: Record<string, string>,
): DialogState {
  return { attempt: previous.attempt + 1, fieldErrors, error: null };
}

export async function addMemory(
  leadId: string,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const back = leadPath(leadId); // throws for a tampered id
  // The twelve keys live in the API, which refuses any other; here a key only has to be chosen.
  const key = text(formData, "key");
  const checked = checkNewMemory(
    {
      key,
      status: text(formData, "status"),
      value: text(formData, "value"),
      quote: text(formData, "quote"),
      reason: text(formData, "reason"),
    },
    key ? [key] : [],
  );
  if (!checked.ok) return invalid(previous, checked.fieldErrors);
  try {
    await apiFetch(`/leads/${leadId}/memory`, {
      method: "POST",
      body: JSON.stringify(checked.body),
    });
  } catch (error) {
    return failure(previous, error);
  }
  redirect(`${back}?done=memory-added#buyer-memory`);
}

export async function confirmMemory(
  leadId: string,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const back = leadPath(leadId);
  const checked = checkConfirm({
    itemId: text(formData, "item_id"),
    quote: text(formData, "quote"),
    value: text(formData, "value"),
  });
  if (!checked.ok) return invalid(previous, checked.fieldErrors);
  try {
    await apiFetch(`/leads/${leadId}/memory/${checked.body.itemId}/confirm`, {
      method: "POST",
      body: JSON.stringify(checked.body.body),
    });
  } catch (error) {
    return failure(previous, error);
  }
  redirect(`${back}?done=memory-confirmed#buyer-memory`);
}

export async function copyMemoryFromLead(
  leadId: string,
  previous: DialogState,
): Promise<DialogState> {
  const back = leadPath(leadId);
  try {
    await apiFetch(`/leads/${leadId}/memory/copy-from-lead`, {
      method: "POST",
    });
  } catch (error) {
    return failure(previous, error);
  }
  redirect(`${back}?done=memory-copied#buyer-memory`);
}
