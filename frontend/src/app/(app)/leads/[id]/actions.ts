"use server";

import { redirect } from "next/navigation";
import { z } from "zod";

import { toErrorInfo } from "@/lib/api-error";
import type { ConversionResult, Lead } from "@/lib/api-types";
import type { DialogState } from "@/lib/dialog-state";
import type { FormState } from "@/lib/form-state";
import type { LeadFormState } from "@/lib/lead-form-state";
import { apiFetch } from "@/lib/server/api";
import {
  type FieldErrors,
  formValues,
  validateLead,
} from "@/lib/validation/lead";
import {
  assignSchema,
  convertPayload,
  convertSchema,
  disqualifySchema,
  fieldErrorsOf,
  qualifySchema,
} from "@/lib/validation/lead-actions";

/**
 * Server Actions for one lead. Each one: validates input, calls the FastAPI endpoint with the
 * user's token, and either returns errors to the form or redirects back to the lead page.
 *
 * The lead ID and version come from the browser, so they are untrusted - that is fine: the
 * API checks that this user may change this lead (tenant, role, ownership) and that the
 * version is current. This code adds no permission logic of its own.
 */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function leadPath(leadId: string): string {
  if (!UUID.test(leadId)) throw new Error("invalid lead id");
  return `/leads/${leadId}`;
}

const failed = (previous: DialogState, error: unknown): DialogState => {
  const info = toErrorInfo(error);
  return {
    attempt: previous.attempt + 1,
    fieldErrors: info.fieldErrors,
    error: info,
  };
};

const invalid = (
  previous: DialogState,
  fieldErrors: Record<string, string>,
): DialogState => ({
  attempt: previous.attempt + 1,
  fieldErrors,
  error: null,
});

export async function updateLead(
  leadId: string,
  previous: LeadFormState,
  formData: FormData,
): Promise<LeadFormState> {
  const path = leadPath(leadId);
  const values = formValues(formData);
  const attempt = previous.attempt + 1;
  const checked = validateLead(values);
  if (!checked.ok)
    return { attempt, values, fieldErrors: checked.errors, error: null };

  // Send every field: an emptied optional field becomes null, i.e. it is cleared.
  const data = checked.data;
  const body = {
    version: Number(formData.get("version")),
    first_name: data.first_name ?? null,
    last_name: data.last_name,
    company_name: data.company_name ?? null,
    email: data.email ?? null,
    phone: data.phone ?? null,
    job_title: data.job_title ?? null,
    source: data.source ?? null,
  };
  try {
    await apiFetch<Lead>(path, { method: "PATCH", body: JSON.stringify(body) });
  } catch (error) {
    const info = toErrorInfo(error);
    return {
      attempt,
      values,
      fieldErrors: info.fieldErrors as FieldErrors,
      error: info,
    };
  }
  redirect(`${path}?done=updated`);
}

export async function assignLead(
  leadId: string,
  previous: DialogState,
  formData: FormData,
) {
  const path = leadPath(leadId);
  const parsed = assignSchema.safeParse({
    owner_id: String(formData.get("owner_id") ?? ""),
    reason: String(formData.get("reason") ?? ""),
  });
  if (!parsed.success) return invalid(previous, fieldErrorsOf(parsed.error));
  try {
    await apiFetch<Lead>(`${path}/assign`, {
      method: "POST",
      body: JSON.stringify(parsed.data),
    });
  } catch (error) {
    return failed(previous, error);
  }
  redirect(`${path}?done=assigned`);
}

export async function markContacted(leadId: string, previous: DialogState) {
  const path = leadPath(leadId);
  try {
    await apiFetch<Lead>(`${path}/status`, {
      method: "POST",
      body: JSON.stringify({ status: "contacted" }),
    });
  } catch (error) {
    return failed(previous, error);
  }
  redirect(`${path}?done=contacted`);
}

export async function qualifyLead(
  leadId: string,
  previous: DialogState,
  formData: FormData,
) {
  const path = leadPath(leadId);
  const parsed = qualifySchema.safeParse({
    reason: String(formData.get("reason") ?? ""),
  });
  if (!parsed.success) return invalid(previous, fieldErrorsOf(parsed.error));
  try {
    await apiFetch<Lead>(`${path}/qualify`, {
      method: "POST",
      body: JSON.stringify(parsed.data),
    });
  } catch (error) {
    return failed(previous, error);
  }
  redirect(`${path}?done=qualified`);
}

export async function disqualifyLead(
  leadId: string,
  previous: DialogState,
  formData: FormData,
) {
  const path = leadPath(leadId);
  const parsed = disqualifySchema.safeParse({
    reason: String(formData.get("reason") ?? ""),
  });
  if (!parsed.success) return invalid(previous, fieldErrorsOf(parsed.error));
  try {
    await apiFetch<Lead>(`${path}/disqualify`, {
      method: "POST",
      body: JSON.stringify(parsed.data),
    });
  } catch (error) {
    return failed(previous, error);
  }
  redirect(`${path}?done=disqualified`);
}

export async function convertLead(
  leadId: string,
  previous: DialogState,
  formData: FormData,
) {
  const path = leadPath(leadId);
  const text = (name: string) => String(formData.get(name) ?? "");
  const parsed = convertSchema.safeParse({
    account_mode: text("account_mode"),
    account_name: text("account_name"),
    existing_account_id: text("existing_account_id"),
    create_opportunity: formData.get("create_opportunity") === "on",
    opportunity_name: text("opportunity_name"),
    amount: text("amount"),
    currency: text("currency"),
    expected_close_date: text("expected_close_date"),
  });
  if (!parsed.success) return invalid(previous, fieldErrorsOf(parsed.error));
  let result: ConversionResult;
  try {
    result = await apiFetch<ConversionResult>(`${path}/convert`, {
      method: "POST",
      body: JSON.stringify(convertPayload(parsed.data)),
    });
  } catch (error) {
    return failed(previous, error);
  }
  redirect(
    `${path}?done=${result.already_converted ? "already_converted" : "converted"}`,
  );
}

const activitySchema = z.object({
  kind: z.enum(["call", "meeting", "email", "note"], {
    message: "Choose the type of activity.",
  }),
  subject: z
    .string()
    .trim()
    .min(1, "Please add a short subject.")
    .max(200, "Subject can be at most 200 characters."),
  body: z
    .string()
    .trim()
    .max(5000, "Notes can be at most 5,000 characters.")
    .transform((v) => (v === "" ? null : v)),
  occurred_at: z
    .string()
    .refine(
      (v) => v === "" || !Number.isNaN(Date.parse(v)),
      "Enter a valid date and time.",
    )
    .refine(
      (v) => v === "" || Date.parse(v) <= Date.now() + 5 * 60_000,
      "An activity that is logged cannot be in the future.",
    )
    .transform((v) => (v === "" ? null : v)),
});

export async function logActivity(
  leadId: string,
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const path = leadPath(leadId);
  const values = Object.fromEntries(
    ["kind", "subject", "body", "occurred_at", "when_local"].map((k) => [
      k,
      String(formData.get(k) ?? ""),
    ]),
  );
  const attempt = previous.attempt + 1;
  const parsed = activitySchema.safeParse(values);
  if (!parsed.success) {
    const fieldErrors: Record<string, string> = {};
    for (const issue of parsed.error.issues)
      fieldErrors[String(issue.path[0])] ??= issue.message;
    return { attempt, values, fieldErrors, error: null };
  }
  const { occurred_at, ...rest } = parsed.data;
  try {
    await apiFetch(`${path}/activities`, {
      method: "POST",
      body: JSON.stringify(occurred_at ? { ...rest, occurred_at } : rest),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return { attempt, values, fieldErrors: info.fieldErrors, error: info };
  }
  redirect(`${path}?done=logged`);
}
