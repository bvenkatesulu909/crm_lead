"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { DialogState } from "@/lib/dialog-state";
import { apiFetch } from "@/lib/server/api";

const EMAIL = /^[^@\s]{1,64}@[^@\s]+\.[^@\s]+$/;
const SLUG = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const text = (formData: FormData, name: string) =>
  String(formData.get(name) ?? "").trim();

/** Super Admin: a new organisation and its first Tenant Admin (who gets an invitation). */
export async function createOrganisation(
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const body = {
    name: text(formData, "name"),
    slug: text(formData, "slug").toLowerCase(),
    admin_email: text(formData, "admin_email"),
    admin_first_name: text(formData, "admin_first_name"),
    admin_last_name: text(formData, "admin_last_name"),
  };
  const errors: Record<string, string> = {};
  if (body.name.length < 2) errors.name = "Enter the organisation's name.";
  if (!SLUG.test(body.slug) || body.slug.length > 63)
    errors.slug =
      "Lower-case letters, digits and single hyphens, e.g. acme-ltd.";
  if (!EMAIL.test(body.admin_email))
    errors.admin_email = "Enter a valid e-mail address.";
  if (!body.admin_first_name)
    errors.admin_first_name = "First name is required.";
  if (!body.admin_last_name) errors.admin_last_name = "Last name is required.";
  if (Object.keys(errors).length)
    return { attempt: previous.attempt + 1, fieldErrors: errors, error: null };
  try {
    await apiFetch("/platform/tenants", {
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
  redirect("/platform?done=created");
}
