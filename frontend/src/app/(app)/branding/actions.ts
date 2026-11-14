"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import {
  TEXT_LIMITS,
  brandingErrorText,
  checkBranding,
  checkLogoFile,
  type Branding,
  type TextField,
} from "@/lib/branding";
import type { FormState } from "@/lib/form-state";
import { apiFetch } from "@/lib/server/api";

/**
 * Branding Server Actions (ADR 0032). The version, the colour and the texts come from the browser
 * and are untrusted: the API checks everything again and decides who may do this. The organisation
 * and the person are never sent - the API takes them from the verified token.
 */
const text = (formData: FormData, name: string) =>
  String(formData.get(name) ?? "");

function failure(
  previous: FormState,
  values: Record<string, string>,
  error: unknown,
): FormState {
  const info = toErrorInfo(error);
  return {
    attempt: previous.attempt + 1,
    values,
    fieldErrors: info.fieldErrors,
    error: { ...info, message: brandingErrorText(info.code, info.message) },
  };
}

export async function saveBranding(
  currentVersion: number,
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  if (!Number.isInteger(currentVersion) || currentVersion < 0)
    throw new Error("invalid version");
  const values: Record<string, string> = {
    primary_color: text(formData, "primary_color"),
  };
  for (const field of Object.keys(TEXT_LIMITS) as TextField[])
    values[field] = text(formData, field);
  const checked = checkBranding(values as Parameters<typeof checkBranding>[0]);
  if (!checked.ok)
    return {
      attempt: previous.attempt + 1,
      values,
      fieldErrors: checked.fieldErrors,
      error: null,
    };
  let saved: Branding;
  try {
    saved = await apiFetch<Branding>("/branding", {
      method: "PUT",
      body: JSON.stringify({
        version: currentVersion,
        primary_color: checked.color,
        about_text: values.about_text,
        terms_text: values.terms_text,
        contact_line: values.contact_line,
        footer_line: values.footer_line,
      }),
    });
  } catch (error) {
    return failure(previous, values, error);
  }
  // Which fields had something taken out (names only) is shown once on the next page.
  const cleaned = saved.cleaned_fields
    .filter((f) => f in TEXT_LIMITS)
    .join(",");
  redirect(`/branding?done=saved${cleaned ? `&cleaned=${cleaned}` : ""}`);
}

export async function uploadLogo(
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const file = formData.get("file");
  if (!(file instanceof File))
    return {
      attempt: previous.attempt + 1,
      values: {},
      fieldErrors: { file: "Choose a logo file." },
      error: null,
    };
  const problem = checkLogoFile(file);
  if (problem)
    return {
      attempt: previous.attempt + 1,
      values: {},
      fieldErrors: { file: problem },
      error: null,
    };
  const body = new FormData();
  body.set("file", file, file.name);
  try {
    await apiFetch("/branding/logo", { method: "PUT", body });
  } catch (error) {
    return failure(previous, {}, error);
  }
  redirect("/branding?done=logo");
}

export async function removeLogo(previous: FormState): Promise<FormState> {
  try {
    await apiFetch("/branding/logo", { method: "DELETE" });
  } catch (error) {
    return failure(previous, {}, error);
  }
  redirect("/branding?done=logo-removed");
}
