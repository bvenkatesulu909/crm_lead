"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import { checkFramework, notesErrorText } from "@/lib/call-notes";
import type { FormState } from "@/lib/form-state";
import { apiFetch } from "@/lib/server/api";

/**
 * Server Action of the call notes settings page (ADR 0035): choose the checklist frame. Only the
 * frame (BANT or MEDDIC) and the version the screen saw are sent; the API checks that this person
 * is an administrator and that nobody else changed the setting in the meantime.
 */
export async function saveFrame(
  version: number,
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const attempt = previous.attempt + 1;
  const chosen = String(formData.get("framework") ?? "");
  const checked = checkFramework(chosen);
  if (!checked.ok)
    return {
      attempt,
      values: { framework: chosen },
      fieldErrors: { framework: checked.message },
      error: null,
    };
  if (!Number.isInteger(version) || version < 0)
    throw new Error("invalid version");
  try {
    await apiFetch("/call-notes/settings", {
      method: "PUT",
      body: JSON.stringify({ framework: checked.value, version }),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return {
      attempt,
      values: { framework: chosen },
      fieldErrors: info.fieldErrors,
      error: {
        ...info,
        message: notesErrorText(info.code, info.message),
      },
    };
  }
  redirect("/automation/call-notes?done=saved");
}
