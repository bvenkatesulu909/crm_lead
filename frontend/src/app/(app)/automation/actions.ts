"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { WorkflowRule } from "@/lib/api-types";
import type { DialogState } from "@/lib/dialog-state";
import type { FormState } from "@/lib/form-state";
import { apiFetch } from "@/lib/server/api";

/**
 * Automation rule Server Actions (tenant admins). The API validates every part of a rule
 * against its catalogue and checks that named colleagues belong to the organisation.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const FIELDS = [
  "name",
  "trigger",
  "days",
  "is_active",
  "conditions_json",
  "actions_json",
] as const;

function read(formData: FormData) {
  const values = Object.fromEntries(
    FIELDS.map((f) => [f, String(formData.get(f) ?? "")]),
  ) as Record<(typeof FIELDS)[number], string>;
  const parse = (text: string): unknown => {
    try {
      return JSON.parse(text || "[]");
    } catch {
      return null;
    }
  };
  const days = values.days.trim() === "" ? null : Number(values.days);
  return {
    values,
    body: {
      name: values.name.trim(),
      trigger: values.trigger,
      days: days !== null && Number.isInteger(days) ? days : null,
      is_active: values.is_active === "on",
      conditions: parse(values.conditions_json),
      actions: parse(values.actions_json),
    },
  };
}

async function save(path: string, method: "POST" | "PUT", previous: FormState, formData: FormData, extra: object = {}): Promise<FormState> {
  const { values, body } = read(formData);
  const attempt = previous.attempt + 1;
  if (!body.name)
    return { attempt, values, fieldErrors: { name: "Give the rule a name." }, error: null };
  let rule: WorkflowRule;
  try {
    rule = await apiFetch<WorkflowRule>(path, { method, body: JSON.stringify({ ...body, ...extra }) });
  } catch (error) {
    const info = toErrorInfo(error);
    return { attempt, values, fieldErrors: info.fieldErrors, error: info };
  }
  redirect(`/automation?done=${method === "POST" ? "created" : "saved"}#rule-${rule.id}`);
} // prettier-ignore

export async function createRule(previous: FormState, formData: FormData) {
  return save("/workflows/rules", "POST", previous, formData);
}

export async function updateRule(
  ruleId: string,
  version: number,
  previous: FormState,
  formData: FormData,
) {
  if (!UUID.test(ruleId) || !Number.isInteger(version))
    throw new Error("invalid rule");
  return save(`/workflows/rules/${ruleId}`, "PUT", previous, formData, {
    version,
  });
}

export async function deleteRule(
  ruleId: string,
  previous: DialogState,
): Promise<DialogState> {
  if (!UUID.test(ruleId)) throw new Error("invalid rule");
  try {
    await apiFetch(`/workflows/rules/${ruleId}`, { method: "DELETE" });
  } catch (error) {
    const info = toErrorInfo(error);
    return {
      attempt: previous.attempt + 1,
      fieldErrors: info.fieldErrors,
      error: info,
    };
  }
  redirect("/automation?done=deleted");
}
