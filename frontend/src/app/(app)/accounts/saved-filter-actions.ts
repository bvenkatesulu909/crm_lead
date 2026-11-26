"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { DialogState } from "@/lib/dialog-state";
import { paramsFromList, type SavedFilter } from "@/lib/saved-filters";
import { apiFetch } from "@/lib/server/api";

/**
 * Saved filter Server Actions. The browser sends only what the person typed: a name, whether to
 * share, and the list's current conditions. Who may share, change or see a filter is decided by
 * the API, never here.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const failed = (previous: DialogState, error: unknown): DialogState => {
  const info = toErrorInfo(error);
  return {
    attempt: previous.attempt + 1,
    fieldErrors: info.fieldErrors,
    error: info,
  };
};

const text = (formData: FormData, name: string) =>
  String(formData.get(name) ?? "").trim();

export async function saveFilter(
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const params = paramsFromList({
    q: text(formData, "q"),
    status: text(formData, "status"),
    segment: text(formData, "segment"),
    country: text(formData, "country"),
    lifecycle: text(formData, "lifecycle"),
  });
  if (Object.keys(params).length === 0) {
    return failed(previous, new Error("Choose at least one filter first."));
  }
  let created: SavedFilter;
  try {
    created = await apiFetch<SavedFilter>("/saved-filters", {
      method: "POST",
      body: JSON.stringify({
        name: text(formData, "name"),
        params,
        shared: formData.get("shared") === "on",
      }),
    });
  } catch (error) {
    return failed(previous, error);
  }
  revalidatePath("/accounts");
  const query = new URLSearchParams();
  for (const key of ["q", "status", "segment", "country", "lifecycle"]) {
    const value = text(formData, key);
    if (value) query.set(key, value);
  }
  redirect(`/accounts?${query.toString()}&saved=${created.id}`);
}

export async function deleteSavedFilter(
  id: string,
  previous: DialogState,
): Promise<DialogState> {
  if (!UUID.test(id)) throw new Error("invalid filter id");
  try {
    await apiFetch<void>(`/saved-filters/${id}`, { method: "DELETE" });
  } catch (error) {
    return failed(previous, error);
  }
  revalidatePath("/accounts");
  redirect("/accounts?done=filter-deleted");
}
