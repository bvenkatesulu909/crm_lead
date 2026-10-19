"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { DialogState } from "@/lib/dialog-state";
import { apiFetch } from "@/lib/server/api";

/**
 * Portal invitations from an account page. The API decides who may invite for which account
 * (admins: any; sales agents: only accounts they own) - no permission logic here.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const EMAIL = /^[^@\s]{1,64}@[^@\s]+\.[^@\s]+$/;
const text = (formData: FormData, name: string) =>
  String(formData.get(name) ?? "").trim();
const check = (value: string) => {
  if (!UUID.test(value)) throw new Error("invalid id");
  return value;
};

function failed(previous: DialogState, error: unknown): DialogState {
  const info = toErrorInfo(error);
  return {
    attempt: previous.attempt + 1,
    fieldErrors: info.fieldErrors,
    error: info,
  };
}

export async function invitePortalUser(
  accountId: string,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const body = {
    email: text(formData, "email"),
    first_name: text(formData, "first_name"),
    last_name: text(formData, "last_name"),
  };
  const errors: Record<string, string> = {};
  if (!EMAIL.test(body.email)) errors.email = "Enter a valid e-mail address.";
  if (!body.first_name) errors.first_name = "First name is required.";
  if (!body.last_name) errors.last_name = "Last name is required.";
  if (Object.keys(errors).length)
    return { attempt: previous.attempt + 1, fieldErrors: errors, error: null };
  try {
    await apiFetch(`/accounts/${check(accountId)}/portal-users`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  } catch (error) {
    return failed(previous, error);
  }
  redirect(`/accounts/${accountId}?done=invited`);
}

export async function revokePortalAccess(
  accountId: string,
  userId: string,
  previous: DialogState,
): Promise<DialogState> {
  try {
    await apiFetch(
      `/accounts/${check(accountId)}/portal-users/${check(userId)}`,
      { method: "DELETE" },
    );
  } catch (error) {
    return failed(previous, error);
  }
  redirect(`/accounts/${accountId}?done=revoked`);
}
