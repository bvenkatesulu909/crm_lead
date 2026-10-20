"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { DialogState } from "@/lib/dialog-state";
import type { FormState } from "@/lib/form-state";
import { apiFetch } from "@/lib/server/api";

/** Knowledge Server Actions (RAG R1). The API re-checks permissions and tenant scope. */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const MAX_BYTES = 20 * 1024 * 1024;

function failed(
  previous: FormState,
  values: Record<string, string>,
  fieldErrors: Record<string, string>,
): FormState {
  return {
    attempt: previous.attempt + 1,
    values,
    fieldErrors,
    error: null,
  };
}

export async function uploadKnowledge(
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const title = String(formData.get("title") ?? "").trim();
  const values = { title };
  const file = formData.get("file");
  if (!(file instanceof File) || file.size === 0)
    return failed(previous, values, { file: "Choose a file." });
  if (file.size > MAX_BYTES)
    return failed(previous, values, { file: "The file is larger than 20 MB." });
  if (title.length > 200)
    return failed(previous, values, { title: "At most 200 characters." });

  const body = new FormData();
  body.set("file", file, file.name);
  if (title) body.set("title", title);
  try {
    await apiFetch("/knowledge/documents", { method: "POST", body });
  } catch (error) {
    const info = toErrorInfo(error);
    return {
      attempt: previous.attempt + 1,
      values,
      fieldErrors: info.fieldErrors,
      error: info,
    };
  }
  revalidatePath("/knowledge");
  redirect("/knowledge?done=uploaded");
}

export async function deleteKnowledge(
  documentId: string,
  previous: DialogState,
): Promise<DialogState> {
  if (!UUID.test(documentId)) throw new Error("invalid document");
  try {
    await apiFetch(`/knowledge/documents/${documentId}`, { method: "DELETE" });
  } catch (error) {
    const info = toErrorInfo(error);
    return {
      attempt: previous.attempt + 1,
      fieldErrors: info.fieldErrors,
      error: info,
    };
  }
  revalidatePath("/knowledge");
  redirect("/knowledge?done=deleted");
}
