"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { DialogState } from "@/lib/dialog-state";
import { apiFetch } from "@/lib/server/api";
import {
  checkRequest,
  webCheckPath,
  type WebCheckRecord,
} from "@/lib/webcheck";

/**
 * Web check Server Action (ADR 0019). The record comes from the page the card sits on and is
 * validated here; the browser sends only the source and the search text. The organisation and
 * the person are never sent: the API takes them from the session. The API also decides whether
 * the person may read the record, whether the source is on, whether the text is valid and
 * whether a limit was reached - and answers with a code this form turns into plain words.
 */
export async function requestWebCheck(
  record: WebCheckRecord,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const back = webCheckPath(record); // throws for a tampered record type or id
  const checked = checkRequest({
    sourceKey: String(formData.get("source_key") ?? ""),
    query: String(formData.get("query") ?? ""),
  });
  if (!checked.ok)
    return {
      attempt: previous.attempt + 1,
      fieldErrors: checked.fieldErrors,
      error: null,
    };
  try {
    await apiFetch("/webcheck/checks", {
      method: "POST",
      body: JSON.stringify({
        target_type: record.type,
        target_id: record.id,
        ...checked.data,
      }),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return {
      attempt: previous.attempt + 1,
      fieldErrors: info.fieldErrors,
      error: info,
    };
  }
  redirect(`${back}?done=webcheck-queued`);
}
