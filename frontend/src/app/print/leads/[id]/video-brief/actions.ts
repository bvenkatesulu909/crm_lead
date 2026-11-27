"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { ScriptRead } from "@/lib/api-types";
import { isUuid } from "@/lib/communications";
import type { DialogState } from "@/lib/dialog-state";
import { leadPath } from "@/lib/qualifier";
import { apiFetch } from "@/lib/server/api";
import { parseChoices } from "@/lib/video-brief";
import { checkScript, scriptErrorText } from "@/lib/video-scripts";

/**
 * Saves a hand-written script (ADR 0041, VB3). The lead id comes from the page and is checked here;
 * the API decides who may write and applies every rule again. Only five fields are ever sent -
 * language, tone, goal, length and the lines - so a tenant, a version, a source or an author in the
 * form is never passed on.
 */

const text = (formData: FormData, name: string) =>
  String(formData.get(name) ?? "");

export async function saveVideoScript(
  leadId: string,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  leadPath(leadId); // throws for a tampered id
  const choices = parseChoices({
    goal: text(formData, "goal"),
    language: text(formData, "language"),
    tone: text(formData, "tone"),
    length: text(formData, "length"),
    quote_id: text(formData, "quote_id"),
  });
  const raw = {
    goal: text(formData, "goal"),
    language: text(formData, "language"),
    tone: text(formData, "tone"),
    length: text(formData, "length"),
  };
  // parseChoices falls back to defaults; here a choice outside the lists is a refusal instead.
  const same =
    choices.goal === raw.goal &&
    choices.language === raw.language &&
    choices.language !== "" &&
    choices.tone === raw.tone &&
    String(choices.length) === raw.length;
  if (!same) {
    return {
      attempt: previous.attempt + 1,
      fieldErrors: {},
      error: {
        status: 422,
        message: "Choose the goal, language, tone and length again.",
        code: null,
        requestId: null,
        fieldErrors: {},
      },
    };
  }
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
    const info = toErrorInfo(error);
    return {
      attempt: previous.attempt + 1,
      fieldErrors: info.fieldErrors,
      error: { ...info, message: scriptErrorText(info.code, info.message) },
    };
  }
  const back = new URLSearchParams({
    goal: choices.goal,
    tone: choices.tone,
    length: String(choices.length),
    language: choices.language,
  });
  if (choices.quoteId && isUuid(choices.quoteId))
    back.set("quote_id", choices.quoteId);
  back.set("saved", String(saved.version));
  redirect(`/print/leads/${leadId}/video-brief?${back.toString()}`);
}
