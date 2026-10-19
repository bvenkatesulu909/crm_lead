"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { Lead } from "@/lib/api-types";
import { apiFetch } from "@/lib/server/api";
import {
  type FieldErrors,
  formValues,
  validateLead,
} from "@/lib/validation/lead";

import type { LeadFormState } from "@/lib/lead-form-state";

/**
 * Server Action behind the "Create lead" form. Runs on the Next.js server:
 * validate again (never trust the browser), call POST /api/v1/leads with the user's token,
 * and either show the backend's errors or go to the lead list.
 */
export async function createLead(
  previous: LeadFormState,
  formData: FormData,
): Promise<LeadFormState> {
  const values = formValues(formData);
  const attempt = previous.attempt + 1;
  const checked = validateLead(values);
  if (!checked.ok)
    return { attempt, values, fieldErrors: checked.errors, error: null };

  let lead: Lead;
  try {
    lead = await apiFetch<Lead>("/leads", {
      method: "POST",
      body: JSON.stringify(checked.data),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return {
      attempt,
      values,
      fieldErrors: info.fieldErrors as FieldErrors,
      error: info,
    };
  }
  redirect(`/leads?created=${encodeURIComponent(lead.id)}`);
}
