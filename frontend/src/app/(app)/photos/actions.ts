"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { DialogState } from "@/lib/dialog-state";
import { photoErrorText } from "@/lib/photo-enhancer";
import { apiFetch } from "@/lib/server/api";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Ask for an adjusted copy of a photo (ADR 0039). Only the photo and the adjustments are sent: the
 * API decides who may do this, which photos qualify, the limits, and refuses an adjustment above
 * its cap or off the list. A success goes back to the photo's page; a refusal is shown there.
 */
export async function createEnhancement(
  documentId: string,
  operations: Record<string, unknown>,
  previous: DialogState,
): Promise<DialogState> {
  if (!UUID.test(documentId)) throw new Error("invalid document id");
  try {
    await apiFetch("/photo-enhancer/enhancements", {
      method: "POST",
      body: JSON.stringify({ document_id: documentId, operations }),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return {
      attempt: previous.attempt + 1,
      fieldErrors: info.fieldErrors,
      error: { ...info, message: photoErrorText(info.code, info.message) },
    };
  }
  redirect(`/photos/${documentId}?done=queued`);
}

/** Delete one adjusted copy (never the original photo). */
export async function deleteEnhancement(
  documentId: string,
  enhancementId: string,
  previous: DialogState,
): Promise<DialogState> {
  if (!UUID.test(documentId) || !UUID.test(enhancementId))
    throw new Error("invalid id");
  try {
    await apiFetch(`/photo-enhancer/enhancements/${enhancementId}`, {
      method: "DELETE",
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return {
      attempt: previous.attempt + 1,
      fieldErrors: info.fieldErrors,
      error: { ...info, message: photoErrorText(info.code, info.message) },
    };
  }
  redirect(`/photos/${documentId}?done=deleted`);
}

/**
 * Choose (or stop choosing) a finished copy for proposal decks (ADR 0039, PE5). Only the choice is
 * sent; the API checks who may do it and that the copy is finished. Nothing reaches a deck that
 * nobody chose.
 */
export async function chooseForDecks(
  enhancementId: string,
  inDecks: boolean,
): Promise<{ error: string | null }> {
  if (!UUID.test(enhancementId)) throw new Error("invalid id");
  try {
    await apiFetch(`/photo-enhancer/enhancements/${enhancementId}`, {
      method: "PATCH",
      body: JSON.stringify({ in_decks: inDecks === true }),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return { error: photoErrorText(info.code, info.message) };
  }
  return { error: null };
}
