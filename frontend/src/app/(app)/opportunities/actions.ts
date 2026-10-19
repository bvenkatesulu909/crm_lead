"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { toErrorInfo, type ApiErrorInfo } from "@/lib/api-error";
import { OPEN_STAGES, type Opportunity } from "@/lib/api-types";
import type { DialogState } from "@/lib/dialog-state";
import type { FormState } from "@/lib/form-state";
import { apiFetch } from "@/lib/server/api";
import { readForm, withoutNulls } from "@/lib/validation/customer-data";
import {
  OPPORTUNITY_FIELDS,
  errorsOf,
  opportunitySchema,
} from "@/lib/validation/pipeline";

/**
 * Opportunity Server Actions. IDs, versions and stages from the browser are untrusted: the
 * API checks this user may change the deal, that the version is current and that the move
 * follows the pipeline rules.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const oppPath = (id: string) => {
  if (!UUID.test(id)) throw new Error("invalid opportunity id");
  return `/opportunities/${id}`;
};
const version = (v: number) => {
  if (!Number.isInteger(v) || v < 1) throw new Error("invalid version");
  return v;
};
const openStage = (value: string) =>
  (OPEN_STAGES as readonly string[]).includes(value) ? value : null;
const text = (formData: FormData, name: string) =>
  String(formData.get(name) ?? "").trim();

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

const invalid = (
  previous: DialogState,
  fieldErrors: Record<string, string>,
): DialogState => ({ attempt: previous.attempt + 1, fieldErrors, error: null });

export async function createOpportunity(
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const values = readForm(formData, OPPORTUNITY_FIELDS);
  const attempt = previous.attempt + 1;
  const parsed = opportunitySchema.safeParse(values);
  if (!parsed.success)
    return {
      attempt,
      values,
      fieldErrors: errorsOf(parsed.error),
      error: null,
    };
  let created: Opportunity;
  try {
    created = await apiFetch<Opportunity>("/opportunities", {
      method: "POST",
      body: JSON.stringify(withoutNulls(parsed.data)),
    });
  } catch (error) {
    return failedForm(attempt, values, error);
  }
  redirect(`/opportunities/${created.id}?done=created`);
}

export async function updateOpportunity(
  opportunityId: string,
  currentVersion: number,
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const path = oppPath(opportunityId);
  const values = readForm(formData, OPPORTUNITY_FIELDS);
  const attempt = previous.attempt + 1;
  const parsed = opportunitySchema.safeParse(values);
  if (!parsed.success)
    return {
      attempt,
      values,
      fieldErrors: errorsOf(parsed.error),
      error: null,
    };
  // The account and stage don't change through the edit form (stage has its own actions).
  const changes: Partial<typeof parsed.data> = { ...parsed.data };
  delete changes.account_id;
  delete changes.stage;
  try {
    await apiFetch(path, {
      method: "PATCH",
      body: JSON.stringify({ version: version(currentVersion), ...changes }),
    });
  } catch (error) {
    return failedForm(attempt, values, error);
  }
  redirect(`${path}?done=updated`);
}

/** For the Kanban board (drag and drop or "Move to"): no redirect, the board refreshes. */
export async function moveOnBoard(
  opportunityId: string,
  currentVersion: number,
  stage: string,
): Promise<{ error: ApiErrorInfo | null }> {
  const path = oppPath(opportunityId);
  const target = openStage(stage);
  if (!target) throw new Error("invalid stage");
  try {
    await apiFetch(`${path}/stage`, {
      method: "POST",
      body: JSON.stringify({ version: version(currentVersion), stage: target }),
    });
  } catch (error) {
    return { error: toErrorInfo(error) };
  }
  revalidatePath("/opportunities");
  return { error: null };
}

export async function moveStage(
  opportunityId: string,
  currentVersion: number,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const path = oppPath(opportunityId);
  const target = openStage(text(formData, "stage"));
  if (!target) return invalid(previous, { stage: "Choose a stage." });
  const note = text(formData, "note");
  if (note.length > 500)
    return invalid(previous, { note: "Note can be at most 500 characters." });
  try {
    await apiFetch(`${path}/stage`, {
      method: "POST",
      body: JSON.stringify({
        version: version(currentVersion),
        stage: target,
        note: note || null,
      }),
    });
  } catch (error) {
    return failed(previous, error);
  }
  redirect(`${path}?done=moved`);
}

export async function markWon(
  opportunityId: string,
  currentVersion: number,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const path = oppPath(opportunityId);
  const note = text(formData, "note");
  if (note.length > 500)
    return invalid(previous, { note: "Note can be at most 500 characters." });
  try {
    await apiFetch(`${path}/won`, {
      method: "POST",
      body: JSON.stringify({
        version: version(currentVersion),
        note: note || null,
      }),
    });
  } catch (error) {
    return failed(previous, error);
  }
  redirect(`${path}?done=won`);
}

export async function markLost(
  opportunityId: string,
  currentVersion: number,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const path = oppPath(opportunityId);
  const reason = text(formData, "reason");
  if (!reason || reason.length > 500)
    return invalid(previous, {
      reason: reason
        ? "Reason can be at most 500 characters."
        : "Please say why the deal was lost.",
    });
  try {
    await apiFetch(`${path}/lost`, {
      method: "POST",
      body: JSON.stringify({ version: version(currentVersion), reason }),
    });
  } catch (error) {
    return failed(previous, error);
  }
  redirect(`${path}?done=lost`);
}

export async function reopenOpportunity(
  opportunityId: string,
  currentVersion: number,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const path = oppPath(opportunityId);
  const target = openStage(text(formData, "stage"));
  if (!target) return invalid(previous, { stage: "Choose a stage." });
  try {
    await apiFetch(`${path}/reopen`, {
      method: "POST",
      body: JSON.stringify({ version: version(currentVersion), stage: target }),
    });
  } catch (error) {
    return failed(previous, error);
  }
  redirect(`${path}?done=reopened`);
}
