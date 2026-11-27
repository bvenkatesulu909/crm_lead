"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { toErrorInfo, type ApiErrorInfo } from "@/lib/api-error";
import type { DialogState } from "@/lib/dialog-state";
import {
  cleanConfirmed,
  cleanSelection,
  cleanWhich,
  isUuid,
  type Batch,
  type BatchEstimate,
  type EstimateResult,
  type StartFailed,
} from "@/lib/research-batches";
import { apiFetch } from "@/lib/server/api";

/**
 * Batch research Server Actions (ADR 0042). The browser sends only which accounts (a saved filter
 * or ticked rows), the "research again" tick and the figure it was shown; the organisation, the
 * person, the cap and every state come from the API, which also decides who may start.
 */

const refused = (message: string): ApiErrorInfo => ({
  status: 422,
  message,
  code: null,
  requestId: null,
  fieldErrors: {},
});

export async function estimateBatch(input: unknown): Promise<EstimateResult> {
  const selection = cleanSelection(input);
  if (selection === null)
    return {
      ok: false,
      error: refused("Choose accounts or a saved filter first."),
    };
  try {
    const estimate = await apiFetch<BatchEstimate>(
      "/research-batches/estimate",
      {
        method: "POST",
        body: JSON.stringify(selection),
      },
    );
    return { ok: true, estimate };
  } catch (error) {
    return { ok: false, error: toErrorInfo(error) };
  }
}

export async function startBatch(
  input: unknown,
  confirmed: unknown,
): Promise<StartFailed> {
  const selection = cleanSelection(input);
  const figure = cleanConfirmed(confirmed);
  if (selection === null || figure === null)
    return { error: refused("Look at the estimate first.") };
  let batch: Batch;
  try {
    batch = await apiFetch<Batch>("/research-batches", {
      method: "POST",
      body: JSON.stringify({
        ...selection,
        confirmed_upper_bound_tokens: figure,
      }),
    });
  } catch (error) {
    return { error: toErrorInfo(error) };
  }
  revalidatePath("/accounts/batches");
  redirect(`/accounts/batches/${batch.id}?done=started`);
}

export async function cancelBatch(
  id: string,
  previous: DialogState,
): Promise<DialogState> {
  if (!isUuid(id)) throw new Error("invalid batch id");
  try {
    await apiFetch<Batch>(`/research-batches/${id}/cancel`, { method: "POST" });
  } catch (error) {
    const info = toErrorInfo(error);
    return { attempt: previous.attempt + 1, fieldErrors: {}, error: info };
  }
  revalidatePath(`/accounts/batches/${id}`);
  redirect(`/accounts/batches/${id}?done=cancel`);
}

export async function estimateRetry(
  id: string,
  which: unknown,
): Promise<EstimateResult> {
  const chosen = cleanWhich(which);
  if (!isUuid(id) || chosen === null)
    return { ok: false, error: refused("Choose which accounts to try again.") };
  try {
    const estimate = await apiFetch<BatchEstimate>(
      `/research-batches/${id}/retry/estimate`,
      { method: "POST", body: JSON.stringify({ which: chosen }) },
    );
    return { ok: true, estimate };
  } catch (error) {
    return { ok: false, error: toErrorInfo(error) };
  }
}

export async function startRetry(
  id: string,
  which: unknown,
  confirmed: unknown,
): Promise<StartFailed> {
  const chosen = cleanWhich(which);
  const figure = cleanConfirmed(confirmed);
  if (!isUuid(id) || chosen === null || figure === null)
    return { error: refused("Look at the estimate first.") };
  let batch: Batch;
  try {
    batch = await apiFetch<Batch>(`/research-batches/${id}/retry`, {
      method: "POST",
      body: JSON.stringify({
        which: chosen,
        confirmed_upper_bound_tokens: figure,
      }),
    });
  } catch (error) {
    return { error: toErrorInfo(error) };
  }
  revalidatePath("/accounts/batches");
  redirect(`/accounts/batches/${batch.id}?done=started`);
}
