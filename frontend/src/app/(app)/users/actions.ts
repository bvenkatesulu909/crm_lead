"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { DialogState } from "@/lib/dialog-state";
import { apiFetch } from "@/lib/server/api";

/**
 * Tenant Admin actions on the Users screen. IDs come from the browser and are untrusted: the
 * API only ever touches users of the admin's own organisation and refuses everything else.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const STAFF_ROLES = new Set([
  "tenant_admin",
  "sales_manager",
  "sales_agent",
  "support_agent",
]);
const EMAIL = /^[^@\s]{1,64}@[^@\s]+\.[^@\s]+$/;

const text = (formData: FormData, name: string) =>
  String(formData.get(name) ?? "").trim();
const id = (value: string) => {
  if (!UUID.test(value)) throw new Error("invalid id");
  return value;
};

const invalid = (
  previous: DialogState,
  fieldErrors: Record<string, string>,
): DialogState => ({ attempt: previous.attempt + 1, fieldErrors, error: null });

async function call(
  previous: DialogState,
  path: string,
  init: RequestInit,
  done: string,
): Promise<DialogState> {
  try {
    await apiFetch(path, init);
  } catch (error) {
    const info = toErrorInfo(error);
    return {
      attempt: previous.attempt + 1,
      fieldErrors: info.fieldErrors,
      error: info,
    };
  }
  redirect(`/users?done=${done}`);
}

function person(formData: FormData) {
  const values = {
    email: text(formData, "email"),
    first_name: text(formData, "first_name"),
    last_name: text(formData, "last_name"),
  };
  const errors: Record<string, string> = {};
  if (!EMAIL.test(values.email)) errors.email = "Enter a valid e-mail address.";
  if (!values.first_name) errors.first_name = "First name is required.";
  if (!values.last_name) errors.last_name = "Last name is required.";
  if (values.first_name.length > 100 || values.last_name.length > 100)
    errors.last_name = "Names can be at most 100 characters.";
  return { values, errors };
}

export async function addStaffUser(
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const { values, errors } = person(formData);
  const role = text(formData, "role");
  if (!STAFF_ROLES.has(role)) errors.role = "Choose a role.";
  if (Object.keys(errors).length) return invalid(previous, errors);
  return call(
    previous,
    "/tenant/users",
    { method: "POST", body: JSON.stringify({ ...values, role }) },
    "added",
  );
}

export async function changeRole(
  userId: string,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const role = text(formData, "role");
  if (!STAFF_ROLES.has(role))
    return invalid(previous, { role: "Choose a role." });
  return call(
    previous,
    `/tenant/users/${id(userId)}/role`,
    { method: "PUT", body: JSON.stringify({ role }) },
    "role",
  );
}

export async function setActive(
  userId: string,
  active: boolean,
  previous: DialogState,
): Promise<DialogState> {
  const action = active ? "reactivate" : "deactivate";
  return call(
    previous,
    `/tenant/users/${id(userId)}/${action}`,
    { method: "POST" },
    action === "reactivate" ? "reactivated" : "deactivated",
  );
}

export async function resendInvite(
  userId: string,
  previous: DialogState,
): Promise<DialogState> {
  return call(
    previous,
    `/tenant/users/${id(userId)}/resend-invite`,
    { method: "POST" },
    "resent",
  );
}

export async function regenerateCode(
  previous: DialogState,
): Promise<DialogState> {
  return call(
    previous,
    "/tenant/signup-code/regenerate",
    { method: "POST" },
    "code",
  );
}

export async function approveRequest(
  requestId: string,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const role = text(formData, "role");
  const accountIds = formData.getAll("account_ids").map(String);
  if (role !== "customer" && !STAFF_ROLES.has(role))
    return invalid(previous, { role: "Choose a role." });
  if (role === "customer" && accountIds.length === 0)
    return invalid(previous, {
      account_ids: "Choose at least one account the customer may see.",
    });
  if (accountIds.some((a) => !UUID.test(a)))
    throw new Error("invalid account id");
  return call(
    previous,
    `/tenant/access-requests/${id(requestId)}/approve`,
    {
      method: "POST",
      body: JSON.stringify({
        role,
        account_ids: role === "customer" ? accountIds : [],
      }),
    },
    "approved",
  );
}

export async function rejectRequest(
  requestId: string,
  previous: DialogState,
): Promise<DialogState> {
  return call(
    previous,
    `/tenant/access-requests/${id(requestId)}/reject`,
    { method: "POST" },
    "rejected",
  );
}
