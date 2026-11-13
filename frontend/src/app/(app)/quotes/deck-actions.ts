"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { DialogState } from "@/lib/dialog-state";
import { deckErrorText } from "@/lib/proposal-decks";
import { apiFetch } from "@/lib/server/api";

/**
 * Ask for a proposal deck of a quote (ADR 0032). Only the quote id is sent: the API decides who
 * may do this, which quotes qualify, and everything the deck contains.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function createProposalDeck(
  quoteId: string,
  previous: DialogState,
): Promise<DialogState> {
  if (!UUID.test(quoteId)) throw new Error("invalid quote id");
  try {
    await apiFetch(`/quotes/${quoteId}/deck`, { method: "POST" });
  } catch (error) {
    const info = toErrorInfo(error);
    return {
      attempt: previous.attempt + 1,
      fieldErrors: info.fieldErrors,
      error: { ...info, message: deckErrorText(info.code, info.message) },
    };
  }
  redirect(`/quotes/${quoteId}?done=deck-queued#deck`);
}
