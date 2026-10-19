"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { Account, DuplicateCheck, TransferResult } from "@/lib/api-types";
import type { DialogState } from "@/lib/dialog-state";
import type { FormState } from "@/lib/form-state";
import { apiFetch } from "@/lib/server/api";
import {
  ACCOUNT_FIELDS,
  accountSchema,
  errorsOf,
  readForm,
  withoutNulls,
} from "@/lib/validation/customer-data";

/**
 * Account Server Actions. IDs and versions come from the browser and are untrusted: the API
 * checks that this user may see and change the account, and the version catches edits made
 * by someone else in the meantime. No permission logic here.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const accountPath = (id: string) => {
  if (!UUID.test(id)) throw new Error("invalid account id");
  return `/accounts/${id}`;
};
const version = (v: number) => {
  if (!Number.isInteger(v) || v < 1) throw new Error("invalid version");
  return v;
};

function failedForm(
  attempt: number,
  values: Record<string, string>,
  error: unknown,
): FormState {
  const info = toErrorInfo(error);
  return { attempt, values, fieldErrors: info.fieldErrors, error: info };
}

const failed = (previous: DialogState, error: unknown): DialogState => {
  const info = toErrorInfo(error);
  return {
    attempt: previous.attempt + 1,
    fieldErrors: info.fieldErrors,
    error: info,
  };
};

const reasonOf = (formData: FormData) =>
  String(formData.get("reason") ?? "").trim();

export async function createAccount(
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const values = readForm(formData, ACCOUNT_FIELDS);
  const attempt = previous.attempt + 1;
  const parsed = accountSchema.safeParse(values);
  if (!parsed.success)
    return {
      attempt,
      values,
      fieldErrors: errorsOf(parsed.error),
      error: null,
    };
  if (formData.get("confirm_new") !== "on") {
    const query = new URLSearchParams({ name: parsed.data.name });
    if (parsed.data.website) query.set("website", parsed.data.website);
    if (parsed.data.phone) query.set("phone", parsed.data.phone);
    const found = await apiFetch<DuplicateCheck>(
      `/accounts/duplicates?${query}`,
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
            href: `/accounts/${c.id}`,
            detail: [c.reasons.join(", "), c.city, c.country]
              .filter(Boolean)
              .join(" · "),
          })),
          hidden: found.hidden_matches,
        },
      };
  }
  let account: Account;
  try {
    account = await apiFetch<Account>("/accounts", {
      method: "POST",
      body: JSON.stringify(withoutNulls(parsed.data)),
    });
  } catch (error) {
    return failedForm(attempt, values, error);
  }
  redirect(`/accounts/${account.id}?done=created`);
}

export async function updateAccount(
  accountId: string,
  currentVersion: number,
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const path = accountPath(accountId);
  const values = readForm(formData, ACCOUNT_FIELDS);
  const attempt = previous.attempt + 1;
  const parsed = accountSchema.safeParse(values);
  if (!parsed.success)
    return {
      attempt,
      values,
      fieldErrors: errorsOf(parsed.error),
      error: null,
    };
  try {
    // Every field of the form is sent; null clears an optional field. The API records only
    // what actually changed.
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

export async function changeAccountStatus(
  accountId: string,
  currentVersion: number,
  target: "active" | "inactive",
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const path = accountPath(accountId);
  if (target !== "active" && target !== "inactive")
    throw new Error("invalid status");
  const reason = reasonOf(formData);
  if (reason.length > 500)
    return {
      attempt: previous.attempt + 1,
      fieldErrors: { reason: "Reason can be at most 500 characters." },
      error: null,
    };
  try {
    await apiFetch(`${path}/status`, {
      method: "POST",
      body: JSON.stringify({
        version: version(currentVersion),
        status: target,
        reason: reason || null,
      }),
    });
  } catch (error) {
    return failed(previous, error);
  }
  redirect(
    `${path}?done=${target === "inactive" ? "deactivated" : "activated"}`,
  );
}

export async function archiveAccount(
  accountId: string,
  currentVersion: number,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const path = accountPath(accountId);
  const reason = reasonOf(formData);
  if (reason.length === 0 || reason.length > 500)
    return {
      attempt: previous.attempt + 1,
      fieldErrors: {
        reason:
          reason.length === 0
            ? "Please say why the account is archived."
            : "Reason can be at most 500 characters.",
      },
      error: null,
    };
  try {
    await apiFetch(`${path}/archive`, {
      method: "POST",
      body: JSON.stringify({ version: version(currentVersion), reason }),
    });
  } catch (error) {
    return failed(previous, error);
  }
  redirect("/accounts?done=archived");
}

export async function restoreAccount(
  accountId: string,
  currentVersion: number,
  previous: DialogState,
): Promise<DialogState> {
  const path = accountPath(accountId);
  try {
    await apiFetch(`${path}/restore`, {
      method: "POST",
      body: JSON.stringify({ version: version(currentVersion) }),
    });
  } catch (error) {
    return failed(previous, error);
  }
  redirect(`${path}?done=restored`);
}

export async function transferAccount(
  accountId: string,
  currentVersion: number,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const path = accountPath(accountId);
  const newOwner = String(formData.get("new_owner_id") ?? "");
  const reason = reasonOf(formData);
  const fieldErrors: Record<string, string> = {};
  if (!UUID.test(newOwner)) fieldErrors.new_owner_id = "Choose the new owner.";
  if (!reason) fieldErrors.reason = "Please give a reason for the transfer.";
  else if (reason.length > 500)
    fieldErrors.reason = "Reason can be at most 500 characters.";
  if (Object.keys(fieldErrors).length > 0)
    return { attempt: previous.attempt + 1, fieldErrors, error: null };
  let result: TransferResult;
  try {
    result = await apiFetch<TransferResult>(`${path}/transfer`, {
      method: "POST",
      body: JSON.stringify({
        version: version(currentVersion),
        new_owner_id: newOwner,
        reason,
        include_contacts: formData.get("include_contacts") === "on",
        include_open_opportunities:
          formData.get("include_open_opportunities") === "on",
        include_open_tasks: formData.get("include_open_tasks") === "on",
      }),
    });
  } catch (error) {
    return failed(previous, error);
  }
  const moved = `${result.contacts_moved}-${result.opportunities_moved}-${result.tasks_moved}`;
  redirect(`${path}?done=transferred&moved=${moved}`);
}
