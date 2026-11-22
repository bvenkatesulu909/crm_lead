"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import { checkSettings, settingsErrorText } from "@/lib/follow-ups";
import type { FormState } from "@/lib/form-state";
import { apiFetch } from "@/lib/server/api";

/**
 * Server Action of the follow-up settings page (ADR 0036). The numbers, the switch and the
 * template come from the form; the version is the one the screen saw. The API checks that this
 * person is an administrator, that the template is an active one of their organisation, that the
 * numbers are inside their bounds and that nobody else changed the settings in the meantime.
 */
export async function saveFollowUpSettings(
  version: number,
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const attempt = previous.attempt + 1;
  if (!Number.isInteger(version) || version < 0)
    throw new Error("invalid version");
  const values: Record<string, string> = {};
  for (const [name, value] of formData.entries())
    if (typeof value === "string") values[name] = value;
  const checked = checkSettings(values);
  if (!checked.ok)
    return { attempt, values, fieldErrors: checked.errors, error: null };
  try {
    await apiFetch("/communications/follow-up-settings", {
      method: "PUT",
      body: JSON.stringify({ ...checked.value, version }),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return {
      attempt,
      values,
      fieldErrors: info.fieldErrors,
      error: { ...info, message: settingsErrorText(info.code, info.message) },
    };
  }
  redirect("/automation/follow-ups?done=saved");
}
