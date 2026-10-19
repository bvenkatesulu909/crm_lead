"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { Contact, DuplicateCheck } from "@/lib/api-types";
import type { DialogState } from "@/lib/dialog-state";
import type { FormState } from "@/lib/form-state";
import { apiFetch } from "@/lib/server/api";
import {
  CONTACT_FIELDS,
  contactSchema,
  errorsOf,
  readForm,
  withCheckboxes,
  withoutNulls,
} from "@/lib/validation/customer-data";

/**
 * Contact Server Actions. IDs and versions from the browser are untrusted: the API decides
 * whether this user may see and change the contact and the account it is linked to.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const contactPath = (id: string) => {
  if (!UUID.test(id)) throw new Error("invalid contact id");
  return `/contacts/${id}`;
};
const version = (v: number) => {
  if (!Number.isInteger(v) || v < 1) throw new Error("invalid version");
  return v;
};
const BOXES = ["is_primary", "do_not_call"] as const;

function read(formData: FormData) {
  return withCheckboxes(readForm(formData, CONTACT_FIELDS), formData, BOXES);
}

function failedForm(
  attempt: number,
  values: Record<string, string>,
  error: unknown,
): FormState {
  const info = toErrorInfo(error);
  return { attempt, values, fieldErrors: info.fieldErrors, error: info };
}

export async function createContact(
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const values = read(formData);
  const attempt = previous.attempt + 1;
  const parsed = contactSchema.safeParse(values);
  if (!parsed.success)
    return {
      attempt,
      values,
      fieldErrors: errorsOf(parsed.error),
      error: null,
    };
  if (formData.get("confirm_new") !== "on") {
    const query = new URLSearchParams({ last_name: parsed.data.last_name });
    if (parsed.data.first_name) query.set("first_name", parsed.data.first_name);
    if (parsed.data.email) query.set("email", parsed.data.email);
    const phone = parsed.data.mobile ?? parsed.data.phone;
    if (phone) query.set("phone", phone);
    const found = await apiFetch<DuplicateCheck>(
      `/contacts/duplicates?${query}`,
    ).catch(() => null);
    if (found && (found.candidates.length > 0 || found.hidden_matches > 0))
      return {
        attempt,
        values,
        fieldErrors: {},
        error: null,
        duplicates: {
          items: found.candidates.map((c) => ({
            label: c.name,
            href: `/contacts/${c.id}`,
            detail: [c.reasons.join(", "), c.email].filter(Boolean).join(" · "),
          })),
          hidden: found.hidden_matches,
        },
      };
  }
  let contact: Contact;
  try {
    contact = await apiFetch<Contact>("/contacts", {
      method: "POST",
      body: JSON.stringify(withoutNulls(parsed.data)),
    });
  } catch (error) {
    return failedForm(attempt, values, error);
  }
  redirect(`/contacts/${contact.id}?done=created`);
}

export async function updateContact(
  contactId: string,
  currentVersion: number,
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const path = contactPath(contactId);
  const values = read(formData);
  const attempt = previous.attempt + 1;
  const parsed = contactSchema.safeParse(values);
  if (!parsed.success)
    return {
      attempt,
      values,
      fieldErrors: errorsOf(parsed.error),
      error: null,
    };
  try {
    await apiFetch(path, {
      method: "PATCH",
      body: JSON.stringify({
        version: version(currentVersion),
        ...parsed.data,
      }),
    });
  } catch (error) {
    return failedForm(attempt, values, error);
  }
  redirect(`${path}?done=updated`);
}

export async function archiveContact(
  contactId: string,
  currentVersion: number,
  returnTo: string | null,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const path = contactPath(contactId);
  const reason = String(formData.get("reason") ?? "").trim();
  if (reason.length > 500)
    return {
      attempt: previous.attempt + 1,
      fieldErrors: { reason: "Reason can be at most 500 characters." },
      error: null,
    };
  try {
    await apiFetch(`${path}/archive`, {
      method: "POST",
      body: JSON.stringify({
        version: version(currentVersion),
        reason: reason || null,
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
  // Back to the account the contact belonged to, if any - never to an arbitrary URL.
  redirect(
    returnTo && UUID.test(returnTo)
      ? `/accounts/${returnTo}?done=updated`
      : "/contacts?done=archived",
  );
}
