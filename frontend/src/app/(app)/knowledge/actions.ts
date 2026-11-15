"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { DialogState } from "@/lib/dialog-state";
import type { FormState } from "@/lib/form-state";
import type { UploadTicket } from "@/lib/direct-upload";
import { apiFetch } from "@/lib/server/api";

/** Knowledge Server Actions (RAG R1). The API re-checks permissions and tenant scope. */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const MAX_BYTES = 20 * 1024 * 1024;

/** What the browser tells us before it sends a knowledge file straight to the store. */
export type KnowledgeUploadInfo = {
  fileName: string;
  size: number;
  title: string;
  visibility: string;
};

export type KnowledgeStartResult =
  | { ticket: UploadTicket }
  | {
      values: Record<string, string>;
      fieldErrors: Record<string, string>;
      error: FormState["error"];
    };

/**
 * Step 1 of a direct upload (ADR 0025): only the name and size reach the web app; the API
 * checks permission, visibility, size and type before it hands out a five-minute link.
 */
export async function startKnowledgeUpload(
  info: KnowledgeUploadInfo,
): Promise<KnowledgeStartResult> {
  const title = String(info?.title ?? "").trim();
  const visibility = String(info?.visibility ?? "internal");
  const values = { title, visibility };
  const refuse = (fieldErrors: Record<string, string>) => ({
    values,
    fieldErrors,
    error: null,
  });
  if (visibility !== "internal" && visibility !== "customer_visible")
    return refuse({ visibility: "Choose who can see it." });
  const fileName = String(info?.fileName ?? "");
  const size = Number(info?.size);
  if (!fileName || !Number.isInteger(size) || size <= 0)
    return refuse({ file: "Choose a file." });
  if (size > MAX_BYTES)
    return refuse({ file: "The file is larger than 20 MB." });
  if (title.length > 200) return refuse({ title: "At most 200 characters." });
  try {
    const ticket = await apiFetch<UploadTicket>("/knowledge/uploads", {
      method: "POST",
      body: JSON.stringify({
        file_name: fileName,
        size_bytes: size,
        visibility,
        ...(title ? { title } : {}),
      }),
    });
    return { ticket };
  } catch (error) {
    const problem = toErrorInfo(error);
    return { values, fieldErrors: problem.fieldErrors, error: problem };
  }
}

/** Step 3: the API reads the file back, checks it and queues it for indexing. */
export async function finishKnowledgeUpload(
  uploadId: string,
  previous: FormState,
): Promise<FormState> {
  if (!UUID.test(uploadId)) throw new Error("invalid upload");
  try {
    await apiFetch(`/knowledge/uploads/${uploadId}/finish`, { method: "POST" });
  } catch (error) {
    const problem = toErrorInfo(error);
    return {
      attempt: previous.attempt + 1,
      values: previous.values,
      fieldErrors: problem.fieldErrors,
      error: problem,
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
