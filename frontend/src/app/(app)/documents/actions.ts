"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { DialogState } from "@/lib/dialog-state";
import { apiFetch } from "@/lib/server/api";

/**
 * Document Server Actions. The record and the document IDs come from the page, but the API
 * checks every one of them again (the record must be visible to the user, or it answers 404).
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const MAX_BYTES = 20 * 1024 * 1024;
export type RecordType = "account" | "opportunity";

function recordPath(type: RecordType, id: string) {
  if (!UUID.test(id) || (type !== "account" && type !== "opportunity"))
    throw new Error("invalid record");
  return type === "account" ? `/accounts/${id}` : `/opportunities/${id}`;
}

const failed = (
  previous: DialogState,
  fieldErrors: Record<string, string>,
): DialogState => ({
  attempt: previous.attempt + 1,
  fieldErrors,
  error: null,
});

export async function uploadDocument(
  recordType: RecordType,
  recordId: string,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const back = recordPath(recordType, recordId);
  const file = formData.get("file");
  if (!(file instanceof File) || file.size === 0)
    return failed(previous, { file: "Choose a file." });
  if (file.size > MAX_BYTES)
    return failed(previous, { file: "The file is larger than 20 MB." });
  const description = String(formData.get("description") ?? "").trim();
  if (description.length > 500)
    return failed(previous, { description: "At most 500 characters." });

  const body = new FormData();
  body.set("record_type", recordType);
  body.set("record_id", recordId);
  body.set("file", file, file.name);
  if (description) body.set("description", description);
  if (recordType === "account" && formData.get("customer_visible") === "on")
    body.set("customer_visible", "true");
  try {
    await apiFetch("/documents", { method: "POST", body });
  } catch (error) {
    const info = toErrorInfo(error);
    return {
      attempt: previous.attempt + 1,
      fieldErrors: info.fieldErrors,
      error: info,
    };
  }
  redirect(`${back}?done=document-uploaded`);
}

export async function deleteDocument(
  recordType: RecordType,
  recordId: string,
  documentId: string,
  previous: DialogState,
): Promise<DialogState> {
  const back = recordPath(recordType, recordId);
  if (!UUID.test(documentId)) throw new Error("invalid document");
  try {
    await apiFetch(`/documents/${documentId}`, { method: "DELETE" });
  } catch (error) {
    const info = toErrorInfo(error);
    return {
      attempt: previous.attempt + 1,
      fieldErrors: info.fieldErrors,
      error: info,
    };
  }
  redirect(`${back}?done=document-deleted`);
}
