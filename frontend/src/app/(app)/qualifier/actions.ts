"use server";

import { redirect } from "next/navigation";

import { toErrorInfo, type ApiErrorInfo } from "@/lib/api-error";
import type { QualifierTrial } from "@/lib/api-types";
import type { DialogState } from "@/lib/dialog-state";
import { isUuid } from "@/lib/communications";
import {
  checkProcedureForm,
  leadPath,
  parseSteps,
  qualifierErrorText,
} from "@/lib/qualifier";
import type { SaveState, TrialState } from "@/lib/qualifier-state";
import { apiFetch } from "@/lib/server/api";

/**
 * Server Actions of the Qualifier (docs/qualifier.md). The lead id and the version come from the
 * browser, so they are untrusted - that is fine: the API checks that the person may read the
 * lead, may use the Qualifier and that the version is current. The organisation and the person
 * are never sent. This code only reads the forms and turns the API's codes into plain words.
 */

function failure(
  previous: { attempt: number },
  error: unknown,
): {
  attempt: number;
  fieldErrors: Record<string, string>;
  error: ApiErrorInfo;
} {
  const info = toErrorInfo(error);
  return {
    attempt: previous.attempt + 1,
    fieldErrors: info.fieldErrors,
    error: {
      ...info,
      message: qualifierErrorText(info.code ?? undefined, info.message),
    },
  };
}

export async function qualifyLead(
  leadId: string,
  previous: DialogState,
): Promise<DialogState> {
  const back = leadPath(leadId); // throws for a tampered id
  try {
    await apiFetch("/qualifier/assessments", {
      method: "POST",
      body: JSON.stringify({ lead_id: leadId }),
      // An AI model can take longer than the default 10 s API timeout (free models often do).
      signal: AbortSignal.timeout(60_000),
    });
  } catch (error) {
    return failure(previous, error);
  }
  redirect(`${back}?done=assessed#qualifier`);
}

export async function saveProcedure(
  replacesVersion: number | null,
  previous: SaveState,
  formData: FormData,
): Promise<SaveState> {
  const values = {
    name: String(formData.get("name") ?? ""),
    steps: String(formData.get("steps") ?? ""),
  };
  const checked = checkProcedureForm(values.name, values.steps);
  if (!checked.ok)
    return {
      attempt: previous.attempt + 1,
      values,
      fieldErrors: checked.fieldErrors,
      error: null,
    };
  try {
    await apiFetch("/qualifier/procedure", {
      method: "PUT",
      body: JSON.stringify({
        ...checked.data,
        ...(replacesVersion === null
          ? {}
          : { replaces_version: replacesVersion }),
      }),
    });
  } catch (error) {
    return { ...failure(previous, error), values };
  }
  redirect("/automation/qualifier?done=saved");
}

export async function deactivateProcedure(
  version: number,
  previous: DialogState,
): Promise<DialogState> {
  try {
    await apiFetch("/qualifier/procedure/deactivate", {
      method: "POST",
      body: JSON.stringify({ version }),
    });
  } catch (error) {
    return failure(previous, error);
  }
  redirect("/automation/qualifier?done=off");
}

/** The dry run: shows the result on the page, changes nothing in the CRM. */
export async function tryProcedure(
  previous: TrialState,
  formData: FormData,
): Promise<TrialState> {
  const leadId = String(formData.get("lead_id") ?? "");
  const useDraft = formData.get("use_draft") === "on";
  const draft = parseSteps(String(formData.get("draft_steps") ?? ""));
  const values = { lead_id: leadId, use_draft: useDraft ? "on" : "off" };
  if (!isUuid(leadId))
    return {
      ...previous,
      attempt: previous.attempt + 1,
      trial: null,
      values,
      fieldErrors: { lead_id: "Choose a lead to try it on." },
      error: null,
    };
  try {
    const trial = await apiFetch<QualifierTrial>("/qualifier/procedure/try", {
      method: "POST",
      body: JSON.stringify({
        lead_id: leadId,
        ...(useDraft && draft.length > 0 ? { steps: draft } : {}),
      }),
      // An AI model can take longer than the default 10 s API timeout (free models often do).
      signal: AbortSignal.timeout(60_000),
    });
    return {
      attempt: previous.attempt + 1,
      fieldErrors: {},
      error: null,
      trial,
      values,
    };
  } catch (error) {
    return { ...failure(previous, error), trial: null, values };
  }
}
