"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { DialogState } from "@/lib/dialog-state";
import type { UploadTicket } from "@/lib/direct-upload";
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

/** What the browser tells us before it sends a file straight to the store (ADR 0025). */
export type UploadInfo = {
  fileName: string;
  size: number;
  description: string;
  customerVisible: boolean;
};

/** Either a ticket for the store, or why not (field errors and/or the API's explanation). */
export type StartResult =
  | { ticket: UploadTicket }
  | { fieldErrors: Record<string, string>; error: DialogState["error"] };

/**
 * Step 1 of a direct upload. Only the file's NAME and SIZE reach the web app - the bytes go
 * from the browser to the store, so Netlify's 6 MB request limit does not apply. The API checks
 * permission, the record, the name, the size and the type before it hands out a link.
 */
export async function startDocumentUpload(
  recordType: RecordType,
  recordId: string,
  info: UploadInfo,
): Promise<StartResult> {
  recordPath(recordType, recordId);
  const fileName = String(info?.fileName ?? "");
  const size = Number(info?.size);
  if (!fileName || !Number.isInteger(size) || size <= 0)
    return { fieldErrors: { file: "Choose a file." }, error: null };
  if (size > MAX_BYTES)
    return {
      fieldErrors: { file: "The file is larger than 20 MB." },
      error: null,
    };
  const description = String(info?.description ?? "").trim();
  if (description.length > 500)
    return {
      fieldErrors: { description: "At most 500 characters." },
      error: null,
    };
  try {
    const ticket = await apiFetch<UploadTicket>("/documents/uploads", {
      method: "POST",
      body: JSON.stringify({
        record_type: recordType,
        record_id: recordId,
        file_name: fileName,
        size_bytes: size,
        customer_visible:
          recordType === "account" && info?.customerVisible === true,
        ...(description ? { description } : {}),
      }),
    });
    return { ticket };
  } catch (error) {
    const problem = toErrorInfo(error);
    return { fieldErrors: problem.fieldErrors, error: problem };
  }
}

/** Step 3: the file is in the store; the API reads it back, checks it and records it. */
export async function finishDocumentUpload(
  recordType: RecordType,
  recordId: string,
  uploadId: string,
  previous: DialogState,
): Promise<DialogState> {
  const back = recordPath(recordType, recordId);
  if (!UUID.test(uploadId)) throw new Error("invalid upload");
  try {
    await apiFetch(`/documents/uploads/${uploadId}/finish`, { method: "POST" });
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
