"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { Quote } from "@/lib/api-types";
import type { DialogState } from "@/lib/dialog-state";
import type { FormState } from "@/lib/form-state";
import { apiFetch } from "@/lib/server/api";
import { quoteErrors, quoteSchema } from "@/lib/validation/quotes";

/**
 * Quote Server Actions. IDs, versions and lines from the browser are untrusted: the API
 * checks access, the version and the workflow, and prices every line from the price book.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const quotePath = (id: string) => {
  if (!UUID.test(id)) throw new Error("invalid quote id");
  return `/quotes/${id}`;
};
const version = (v: number) => {
  if (!Number.isInteger(v) || v < 1) throw new Error("invalid version");
  return v;
};
const FIELDS = [
  "account_id",
  "title",
  "price_book_id",
  "opportunity_id",
  "contact_id",
  "valid_until",
  "customer_note",
  "internal_note",
  "lines_json",
] as const;

function read(formData: FormData) {
  const values = Object.fromEntries(
    FIELDS.map((f) => [f, String(formData.get(f) ?? "")]),
  ) as Record<(typeof FIELDS)[number], string>;
  let lines: unknown = [];
  try {
    lines = JSON.parse(values.lines_json || "[]");
  } catch {
    lines = null;
  }
  return { values, input: { ...values, lines } };
}

export async function createQuote(
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const { values, input } = read(formData);
  const attempt = previous.attempt + 1;
  const parsed = quoteSchema.safeParse(input);
  if (!parsed.success)
    return {
      attempt,
      values,
      fieldErrors: quoteErrors(parsed.error),
      error: null,
    };
  let quote: Quote;
  try {
    quote = await apiFetch<Quote>("/quotes", {
      method: "POST",
      body: JSON.stringify(parsed.data),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return { attempt, values, fieldErrors: info.fieldErrors, error: info };
  }
  redirect(`/quotes/${quote.id}?done=created`);
}

export async function updateQuote(
  quoteId: string,
  currentVersion: number,
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const path = quotePath(quoteId);
  const { values, input } = read(formData);
  const attempt = previous.attempt + 1;
  const parsed = quoteSchema.safeParse(input);
  if (!parsed.success)
    return {
      attempt,
      values,
      fieldErrors: quoteErrors(parsed.error),
      error: null,
    };
  const { account_id: _ignored, ...changes } = parsed.data;
  void _ignored; // the account of a quote never changes
  try {
    await apiFetch(path, {
      method: "PATCH",
      body: JSON.stringify({ version: version(currentVersion), ...changes }),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return { attempt, values, fieldErrors: info.fieldErrors, error: info };
  }
  redirect(`${path}?done=updated`);
}

const STEPS = {
  submit: { needsReason: false, done: "submitted" },
  approve: { needsReason: false, done: "approved" },
  reject: { needsReason: true, done: "rejected" },
  send: { needsReason: false, done: "sent" },
  accept: { needsReason: false, done: "accepted" },
  decline: { needsReason: true, done: "declined" },
  revise: { needsReason: false, done: "revised" },
  order: { needsReason: false, done: "ordered" },
} as const;
export type QuoteStep = keyof typeof STEPS;

/** One workflow step (submit, approve, reject, send, accept, decline, revise, order). */
export async function quoteStep(
  quoteId: string,
  currentVersion: number,
  step: QuoteStep,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const path = quotePath(quoteId);
  const rule = STEPS[step];
  if (!rule) throw new Error("invalid step");
  const text = String(
    formData.get(rule.needsReason ? "reason" : "note") ?? "",
  ).trim();
  const reference = String(formData.get("customer_reference") ?? "").trim();
  if (rule.needsReason && !text)
    return {
      attempt: previous.attempt + 1,
      fieldErrors: { reason: "Please give a reason." },
      error: null,
    };
  if (text.length > 500 || reference.length > 100)
    return {
      attempt: previous.attempt + 1,
      fieldErrors: {
        [rule.needsReason ? "reason" : "note"]: "This text is too long.",
      },
      error: null,
    };
  const body: Record<string, unknown> = { version: version(currentVersion) };
  if (step === "order") body.customer_reference = reference || null;
  else if (step !== "revise")
    body[rule.needsReason ? "reason" : "note"] = text || null;
  let result: Quote;
  try {
    result = await apiFetch<Quote>(`${path}/${step}`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return {
      attempt: previous.attempt + 1,
      fieldErrors: info.fieldErrors,
      error: info,
    };
  }
  // A revision is a new quote; everything else stays on this one.
  redirect(`/quotes/${result.id}?done=${rule.done}`);
}

/** "Send by e-mail": the API picks the recipient (the quote's contact) - never the browser. */
export async function emailQuote(
  quoteId: string,
  currentVersion: number,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const path = quotePath(quoteId);
  const message = String(formData.get("message") ?? "").trim();
  if (message.length > 500)
    return {
      attempt: previous.attempt + 1,
      fieldErrors: { message: "The message can be at most 500 characters." },
      error: null,
    };
  try {
    await apiFetch(`${path}/email`, {
      method: "POST",
      body: JSON.stringify({
        version: version(currentVersion),
        message: message || null,
      }),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return {
      attempt: previous.attempt + 1,
      fieldErrors: info.fieldErrors,
      error: info,
    };
  }
  redirect(`${path}?done=emailed`);
}

/** Tenant admins change the discount above which quotes need approval (the API checks). */
export async function updateQuoteSettings(
  currentVersion: number,
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const value = String(formData.get("approval_limit_percent") ?? "")
    .trim()
    .replace(",", ".");
  const values = { approval_limit_percent: value };
  const attempt = previous.attempt + 1;
  if (!/^\d{1,3}(\.\d{1,2})?$/.test(value) || Number(value) > 100)
    return {
      attempt,
      values,
      fieldErrors: {
        approval_limit_percent:
          "Enter a percentage from 0 to 100 (up to 2 decimals).",
      },
      error: null,
    };
  if (!Number.isInteger(currentVersion) || currentVersion < 0)
    throw new Error("invalid version");
  try {
    await apiFetch("/quotes/settings", {
      method: "PUT",
      body: JSON.stringify({
        version: currentVersion,
        approval_limit_percent: value,
      }),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return { attempt, values, fieldErrors: info.fieldErrors, error: info };
  }
  redirect("/quotes/settings?done=saved");
}
