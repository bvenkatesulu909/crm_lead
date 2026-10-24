"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { Contract } from "@/lib/api-types";
import type { DialogState } from "@/lib/dialog-state";
import type { FormState } from "@/lib/form-state";
import { apiFetch } from "@/lib/server/api";
import {
  activeContractSchema,
  contractErrors,
  contractSchema,
  draftContractSchema,
} from "@/lib/validation/contracts";

/**
 * Contract Server Actions. IDs and versions from the browser are untrusted: the API checks
 * access, the version and the status flow, and the account, contact, deal and quote links.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const contractPath = (id: string) => {
  if (!UUID.test(id)) throw new Error("invalid contract id");
  return `/contracts/${id}`;
};
const version = (v: number) => {
  if (!Number.isInteger(v) || v < 1) throw new Error("invalid version");
  return v;
};
const FIELDS = [
  "account_id",
  "title",
  "start_date",
  "end_date",
  "total_value",
  "currency",
  "billing_frequency",
  "auto_renew",
  "renewal_notice_days",
  "renewal_term_months",
  "terms",
] as const;

function read(formData: FormData) {
  return Object.fromEntries(
    FIELDS.map((f) => [f, String(formData.get(f) ?? "")]),
  ) as Record<(typeof FIELDS)[number], string>;
}

export async function createContract(
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const values = {
    ...read(formData),
    account_label: String(formData.get("account_label") ?? ""),
  };
  const attempt = previous.attempt + 1;
  const parsed = contractSchema.safeParse(values);
  if (!parsed.success)
    return {
      attempt,
      values,
      fieldErrors: contractErrors(parsed.error),
      error: null,
    };
  let contract: Contract;
  try {
    contract = await apiFetch<Contract>("/contracts", {
      method: "POST",
      body: JSON.stringify(parsed.data),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return { attempt, values, fieldErrors: info.fieldErrors, error: info };
  }
  redirect(`/contracts/${contract.id}?done=created`);
}

/** Drafts change freely; an active contract changes only what renewing is not needed for. */
export async function updateContract(
  contractId: string,
  currentVersion: number,
  mode: "draft" | "active",
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const path = contractPath(contractId);
  if (mode !== "draft" && mode !== "active") throw new Error("invalid mode");
  const values = read(formData);
  const attempt = previous.attempt + 1;
  const parsed =
    mode === "draft"
      ? draftContractSchema.safeParse(values)
      : activeContractSchema.safeParse(values);
  if (!parsed.success)
    return {
      attempt,
      values,
      fieldErrors: contractErrors(parsed.error),
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
    const info = toErrorInfo(error);
    return { attempt, values, fieldErrors: info.fieldErrors, error: info };
  }
  redirect(`${path}?done=updated`);
}

const STEPS = {
  activate: { done: "activated", field: "note" },
  terminate: { done: "terminated", field: "reason" },
  renew: { done: "renewed", field: "note" },
  note: { done: "noted", field: "note" },
} as const;
export type ContractStep = keyof typeof STEPS;

const optional = (formData: FormData, name: string) => {
  const text = String(formData.get(name) ?? "").trim();
  return text === "" ? null : text;
};

/** One step: activate, terminate (needs a reason), renew (creates a new draft) or add a note. */
export async function contractStep(
  contractId: string,
  currentVersion: number,
  step: ContractStep,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const path = contractPath(contractId);
  const rule = STEPS[step];
  if (!rule) throw new Error("invalid step");
  const attempt = previous.attempt + 1;
  const text = optional(formData, rule.field);
  if ((step === "terminate" || step === "note") && !text)
    return {
      attempt,
      fieldErrors: {
        [rule.field]:
          step === "terminate" ? "Please give a reason." : "Write a note.",
      },
      error: null,
    };
  if (text && text.length > 500)
    return {
      attempt,
      fieldErrors: { [rule.field]: "This text is too long (500 characters)." },
      error: null,
    };

  let url = `${path}/${step === "note" ? "notes" : step}`;
  let body: Record<string, unknown>;
  if (step === "note") body = { note: text };
  else if (step === "terminate")
    body = { version: version(currentVersion), reason: text };
  else if (step === "renew") {
    const start = optional(formData, "start_date");
    const end = optional(formData, "end_date");
    const value = optional(formData, "total_value")?.replace(",", ".") ?? null;
    const problems: Record<string, string> = {};
    if (start && !/^\d{4}-\d{2}-\d{2}$/.test(start))
      problems.start_date = "Enter a date.";
    if (end && !/^\d{4}-\d{2}-\d{2}$/.test(end))
      problems.end_date = "Enter a date.";
    if (start && end && end < start)
      problems.end_date = "The end date cannot be before the start date.";
    if (value && !/^\d{1,14}(\.\d{1,2})?$/.test(value))
      problems.total_value = "Enter an amount such as 12000.50.";
    if (Object.keys(problems).length > 0)
      return { attempt, fieldErrors: problems, error: null };
    body = {
      version: version(currentVersion),
      start_date: start,
      end_date: end,
      total_value: value,
      note: text,
    };
  } else body = { version: version(currentVersion), note: text };
  url = url.replace(/\/$/, "");

  let result: Contract;
  try {
    result = await apiFetch<Contract>(url, {
      method: "POST",
      body: JSON.stringify(body),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return { attempt, fieldErrors: info.fieldErrors, error: info };
  }
  // A renewal is a new contract; everything else stays on this one.
  redirect(`/contracts/${result.id}?done=${rule.done}`);
}
