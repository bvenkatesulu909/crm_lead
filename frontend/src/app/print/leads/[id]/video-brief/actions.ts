"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { ScriptRead } from "@/lib/api-types";
import { isUuid } from "@/lib/communications";
import type { DialogState } from "@/lib/dialog-state";
import { leadPath } from "@/lib/qualifier";
import { apiFetch } from "@/lib/server/api";
import { strictChoices } from "@/lib/video-brief";
import {
  checkScript,
  scriptErrorText,
  type DraftState,
} from "@/lib/video-scripts";

/**
 * The video brief's Server Actions (ADR 0041): save a hand-written script (VB3), ask the drafter for
 * a draft and send a script to the approval queue (VB5). The lead id comes from the page and is
 * checked here; the API decides who may do what and applies every rule again. Only the documented
 * fields are ever sent, so a tenant, a version, a source, an author or an agent in the form is never
 * passed on.
 */

const text = (formData: FormData, name: string) =>
  String(formData.get(name) ?? "");

const NO_CHOICE = {
  status: 422,
  message: "Choose the goal, language, tone and length again.",
  code: null,
  requestId: null,
  fieldErrors: {},
};

function choicesOf(formData: FormData) {
  return strictChoices({
    goal: text(formData, "goal"),
    language: text(formData, "language"),
    tone: text(formData, "tone"),
    length: text(formData, "length"),
    quote_id: text(formData, "quote_id"),
  });
}

function failure(previous: DialogState, error: unknown): DialogState {
  const info = toErrorInfo(error);
  return {
    attempt: previous.attempt + 1,
    fieldErrors: info.fieldErrors,
    error: { ...info, message: scriptErrorText(info.code, info.message) },
  };
}

const noChoice = (previous: DialogState): DialogState => ({
  attempt: previous.attempt + 1,
  fieldErrors: {},
  error: NO_CHOICE,
});

/** The page address after an action: the same choices, plus one notice. */
function backTo(
  leadId: string,
  choices: NonNullable<ReturnType<typeof choicesOf>>,
  notice: [string, string],
): string {
  const back = new URLSearchParams({
    goal: choices.goal,
    tone: choices.tone,
    length: String(choices.length),
    language: choices.language,
  });
  if (choices.quoteId && isUuid(choices.quoteId))
    back.set("quote_id", choices.quoteId);
  back.set(notice[0], notice[1]);
  return `/print/leads/${leadId}/video-brief?${back.toString()}`;
}

export async function saveVideoScript(
  leadId: string,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  leadPath(leadId); // throws for a tampered id
  const choices = choicesOf(formData);
  if (!choices) return noChoice(previous);
  const checked = checkScript(text(formData, "lines"), choices.length);
  if (!checked.ok)
    return {
      attempt: previous.attempt + 1,
      fieldErrors: checked.fieldErrors,
      error: null,
    };
  let saved: ScriptRead;
  try {
    saved = await apiFetch<ScriptRead>(`/leads/${leadId}/video-scripts`, {
      method: "POST",
      body: JSON.stringify({
        language: choices.language,
        tone: choices.tone,
        goal: choices.goal,
        length_seconds: choices.length,
        lines: checked.lines,
      }),
    });
  } catch (error) {
    return failure(previous, error);
  }
  redirect(backTo(leadId, choices, ["saved", String(saved.version)]));
}

/** Asks the drafter for a script. Only the choices are sent - the server reads the facts. The
 * answer is a draft: nothing is saved or approved. */
export async function draftVideoScript(
  leadId: string,
  previous: DraftState,
  formData: FormData,
): Promise<DraftState> {
  leadPath(leadId);
  const choices = choicesOf(formData);
  if (!choices) return { ...noChoice(previous), draft: null };
  try {
    const answer = await apiFetch<{
      lines: string[];
      words: number;
      reason: string;
    }>(`/leads/${leadId}/video-brief/draft`, {
      method: "POST",
      body: JSON.stringify({
        goal: choices.goal,
        language: choices.language,
        tone: choices.tone,
        length_seconds: choices.length,
        ...(choices.quoteId ? { quote_id: choices.quoteId } : {}),
      }),
    });
    return {
      attempt: previous.attempt + 1,
      fieldErrors: {},
      error: null,
      draft: {
        lines: answer.lines,
        words: answer.words,
        reason: answer.reason,
      },
    };
  } catch (error) {
    return { ...failure(previous, error), draft: null };
  }
}

/** Sends the script in the box to the approval queue. The server reads the facts again and runs
 * every check of the drafter on the lines; a different person must approve before it is saved. */
export async function proposeVideoScript(
  leadId: string,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  leadPath(leadId);
  const choices = choicesOf(formData);
  if (!choices) return noChoice(previous);
  const checked = checkScript(text(formData, "lines"), choices.length);
  if (!checked.ok)
    return {
      attempt: previous.attempt + 1,
      fieldErrors: checked.fieldErrors,
      error: null,
    };
  let answer: {
    outcome: string;
    proposal_id: string | null;
    blocked_message: string | null;
  };
  try {
    answer = await apiFetch(`/leads/${leadId}/video-brief/propose`, {
      method: "POST",
      body: JSON.stringify({
        goal: choices.goal,
        language: choices.language,
        tone: choices.tone,
        length_seconds: choices.length,
        lines: checked.lines,
        ...(choices.quoteId ? { quote_id: choices.quoteId } : {}),
      }),
    });
  } catch (error) {
    return failure(previous, error);
  }
  if (answer.outcome !== "proposed" || !answer.proposal_id)
    return {
      attempt: previous.attempt + 1,
      fieldErrors: {},
      error: {
        ...NO_CHOICE,
        message:
          answer.blocked_message ??
          "The safety check refused this script. Change it and try again.",
      },
    };
  redirect(backTo(leadId, choices, ["proposed", answer.proposal_id]));
}
