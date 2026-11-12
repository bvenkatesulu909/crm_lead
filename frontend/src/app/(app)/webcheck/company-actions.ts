"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import { askErrorText, checkApply, saveErrorText } from "@/lib/company-details";
import type { DialogState } from "@/lib/dialog-state";
import { leadPath } from "@/lib/qualifier";
import { apiFetch } from "@/lib/server/api";

/**
 * Company details Server Actions (BP-02, ADR 0026). The lead id comes from the page and is checked
 * here; the API decides whether the person may read and change the lead, which website is read
 * and whether the feature is on. Asking sends ONLY the lead; saving sends the lead, the evidence,
 * the version and the NAMES of the fields to keep - the values come from the stored evidence on
 * the server, so a changed form cannot put a value of its own on the lead.
 */

function failure(
  previous: DialogState,
  error: unknown,
  words: (code: string | null, fallback: string) => string,
): DialogState {
  const info = toErrorInfo(error);
  return {
    attempt: previous.attempt + 1,
    fieldErrors: info.fieldErrors,
    error: { ...info, message: words(info.code, info.message) },
  };
}

export async function askCompanyDetails(
  leadId: string,
  previous: DialogState,
): Promise<DialogState> {
  const back = leadPath(leadId); // throws for a tampered id
  try {
    await apiFetch("/webcheck/company-details", {
      method: "POST",
      body: JSON.stringify({ lead_id: leadId }),
    });
  } catch (error) {
    return failure(previous, error, askErrorText);
  }
  redirect(`${back}?done=company-queued#company-details`);
}

export async function applyCompanyDetails(
  leadId: string,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const back = leadPath(leadId);
  const checked = checkApply({
    fields: formData.getAll("field").map(String),
    version: String(formData.get("version") ?? ""),
    evidenceId: String(formData.get("evidence_id") ?? ""),
  });
  if (!checked.ok)
    return {
      attempt: previous.attempt + 1,
      fieldErrors: { field: checked.message },
      error: null,
    };
  try {
    await apiFetch("/webcheck/company-details/apply", {
      method: "POST",
      body: JSON.stringify({
        lead_id: leadId,
        evidence_id: checked.evidenceId,
        fields: checked.fields,
        version: checked.version,
      }),
    });
  } catch (error) {
    return failure(previous, error, saveErrorText);
  }
  redirect(`${back}?done=company-saved#company-details`);
}
