"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { DialogState } from "@/lib/dialog-state";
import type { FormState } from "@/lib/form-state";
import { apiFetch } from "@/lib/server/api";
import {
  activityPayload,
  activitySchema,
  errorsOf,
} from "@/lib/validation/pipeline";

/**
 * Activity and task Server Actions. Record IDs, versions and the page to return to come from
 * the browser and are untrusted: IDs are format-checked here and the API decides whether
 * this user may see the record and change the activity. Return paths are limited to CRM
 * pages so a crafted form can't send the user elsewhere.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const RETURN =
  /^\/(tasks(\/calendar)?|(leads|accounts|contacts|opportunities)\/[0-9a-f-]{36})$/i;
const LINKS = {
  lead: "lead_id",
  account: "account_id",
  contact: "contact_id",
  opportunity: "opportunity_id",
} as const;
export type ActivityLink = { type: keyof typeof LINKS; id: string } | null;

const back = (path: string, done: string) =>
  `${RETURN.test(path) ? path : "/tasks"}?done=${done}`;
const activityPath = (id: string) => {
  if (!UUID.test(id)) throw new Error("invalid activity id");
  return `/activities/${id}`;
};
const version = (v: number) => {
  if (!Number.isInteger(v) || v < 1) throw new Error("invalid version");
  return v;
};
const FIELDS = [
  "kind",
  "subject",
  "body",
  "status",
  "priority",
  "due_at",
  "reminder_at",
  "occurred_at",
  "outcome",
  "assignee_id",
] as const;

export async function createActivity(
  link: ActivityLink,
  returnTo: string,
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const values: Record<string, string> = {};
  for (const f of [
    ...FIELDS,
    "due_local",
    "occurred_local",
    "reminder_offset",
  ]) {
    const value = formData.get(f);
    if (value !== null) values[f] = String(value);
  }
  const attempt = previous.attempt + 1;
  // The form shows only the fields of the chosen mode (plan vs log); the others count as
  // empty. Priority and assignee stay optional (left out = API default).
  const input: Record<string, string> = Object.fromEntries(
    FIELDS.filter((f) => f !== "priority" && f !== "assignee_id").map((f) => [
      f,
      values[f] ?? "",
    ]),
  );
  if (values.priority) input.priority = values.priority;
  if (values.assignee_id !== undefined) input.assignee_id = values.assignee_id;
  const parsed = activitySchema.safeParse(input);
  if (!parsed.success)
    return {
      attempt,
      values,
      fieldErrors: errorsOf(parsed.error),
      error: null,
    };
  if (link && (!(link.type in LINKS) || !UUID.test(link.id)))
    throw new Error("invalid record link");
  const body = {
    ...activityPayload(parsed.data),
    ...(link ? { [LINKS[link.type]]: link.id } : {}),
  };
  try {
    await apiFetch("/activities", {
      method: "POST",
      body: JSON.stringify(body),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return { attempt, values, fieldErrors: info.fieldErrors, error: info };
  }
  // The header bell lives in the shared layout, which Next.js keeps between pages:
  // reload it so the count is right after this change.
  revalidatePath("/", "layout");
  redirect(
    back(returnTo, parsed.data.status === "open" ? "planned" : "logged"),
  );
}

async function change(
  activityId: string,
  step: "complete" | "cancel" | "reopen",
  payload: Record<string, unknown>,
  returnTo: string,
  previous: DialogState,
): Promise<DialogState> {
  try {
    await apiFetch(`${activityPath(activityId)}/${step}`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return {
      attempt: previous.attempt + 1,
      fieldErrors: info.fieldErrors,
      error: info,
    };
  }
  // The header bell lives in the shared layout, which Next.js keeps between pages:
  // reload it so the count is right after this change.
  revalidatePath("/", "layout");
  redirect(
    back(
      returnTo,
      step === "complete"
        ? "completed"
        : step === "cancel"
          ? "cancelled"
          : "reopened",
    ),
  );
}

export async function completeActivity(
  activityId: string,
  currentVersion: number,
  returnTo: string,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const outcome = String(formData.get("outcome") ?? "").trim();
  if (outcome.length > 500)
    return {
      attempt: previous.attempt + 1,
      fieldErrors: { outcome: "Outcome can be at most 500 characters." },
      error: null,
    };
  return change(
    activityId,
    "complete",
    { version: version(currentVersion), outcome: outcome || null },
    returnTo,
    previous,
  );
}

export async function cancelActivity(
  activityId: string,
  currentVersion: number,
  returnTo: string,
  previous: DialogState,
): Promise<DialogState> {
  return change(
    activityId,
    "cancel",
    { version: version(currentVersion) },
    returnTo,
    previous,
  );
}

export async function reopenActivity(
  activityId: string,
  currentVersion: number,
  returnTo: string,
  previous: DialogState,
): Promise<DialogState> {
  return change(activityId, "reopen", { version: version(currentVersion) }, returnTo, previous);
} // prettier-ignore
