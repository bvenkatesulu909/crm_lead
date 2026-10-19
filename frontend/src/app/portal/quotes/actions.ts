"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { DialogState } from "@/lib/dialog-state";
import { apiFetch } from "@/lib/server/api";

/**
 * Customer answers to a quote. The API accepts the answer only for a SENT, unexpired quote of
 * this customer's own company, with the current version.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function answerQuote(
  quoteId: string,
  currentVersion: number,
  accepted: boolean,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  if (!UUID.test(quoteId)) throw new Error("invalid quote id");
  if (!Number.isInteger(currentVersion) || currentVersion < 1)
    throw new Error("invalid version");
  const text = String(formData.get(accepted ? "note" : "reason") ?? "").trim();
  if (!accepted && !text)
    return {
      attempt: previous.attempt + 1,
      fieldErrors: { reason: "Please tell us why, so we can do better." },
      error: null,
    };
  if (text.length > 500)
    return {
      attempt: previous.attempt + 1,
      fieldErrors: {
        [accepted ? "note" : "reason"]: "At most 500 characters.",
      },
      error: null,
    };
  try {
    await apiFetch(
      `/portal/quotes/${quoteId}/${accepted ? "accept" : "decline"}`,
      {
        method: "POST",
        body: JSON.stringify(
          accepted
            ? { version: currentVersion, note: text || null }
            : { version: currentVersion, reason: text },
        ),
      },
    );
  } catch (error) {
    const info = toErrorInfo(error);
    return {
      attempt: previous.attempt + 1,
      fieldErrors: info.fieldErrors,
      error: info,
    };
  }
  redirect(
    `/portal/quotes/${quoteId}?done=${accepted ? "accepted" : "declined"}`,
  );
}
