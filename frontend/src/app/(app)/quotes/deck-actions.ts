"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { DialogState } from "@/lib/dialog-state";
import {
  deckErrorText,
  deckQuery,
  parseDeckFormat,
  summaryErrorText,
  type DeckFormat,
  type SummaryDraft,
} from "@/lib/proposal-decks";
import { apiFetch } from "@/lib/server/api";

/**
 * Ask for a proposal deck of a quote (ADR 0032), as a PDF or a PowerPoint file. Only the quote id
 * and the format are sent: the API decides who may do this, which quotes qualify, and everything
 * the deck contains.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function createProposalDeck(
  quoteId: string,
  format: DeckFormat,
  previous: DialogState,
): Promise<DialogState> {
  if (!UUID.test(quoteId)) throw new Error("invalid quote id");
  if (format !== parseDeckFormat(format)) throw new Error("invalid format");
  try {
    await apiFetch(`/quotes/${quoteId}/deck${deckQuery(format)}`, {
      method: "POST",
    });
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

/**
 * Ask the deck writer to draft the "why this proposal" slide (ADR 0032 Amendment A, PD7). Only the
 * quote id is sent. The draft becomes a proposal in the approval queue: a different person approves
 * it there, and only an approved text is drawn into the next deck. A text the safety check refuses
 * is shown with its reason instead.
 */
export async function draftDeckSummary(
  quoteId: string,
  previous: DialogState,
): Promise<DialogState> {
  if (!UUID.test(quoteId)) throw new Error("invalid quote id");
  let draft: SummaryDraft;
  try {
    draft = await apiFetch<SummaryDraft>(
      `/quotes/${quoteId}/deck/summary-draft`,
      { method: "POST" },
    );
  } catch (error) {
    const info = toErrorInfo(error);
    return {
      attempt: previous.attempt + 1,
      fieldErrors: info.fieldErrors,
      error: { ...info, message: summaryErrorText(info.code, info.message) },
    };
  }
  if (
    draft.outcome === "proposed" &&
    draft.proposal_id &&
    UUID.test(draft.proposal_id)
  ) {
    redirect(`/approvals/${draft.proposal_id}`);
  }
  if (draft.outcome === "proposed") throw new Error("invalid proposal id");
  return {
    attempt: previous.attempt + 1,
    fieldErrors: {},
    error: {
      code: "proposal_blocked",
      message: `The safety check blocked the draft: ${draft.blocked_message ?? "no reason was given."}`,
      fieldErrors: {},
      requestId: "",
      status: 422,
    },
  };
}
