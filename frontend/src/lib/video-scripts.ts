/** Words and checks for writing and saving a buyer-video script (ADR 0041, VB3). The API decides
 * everything that matters (it cleans the text and refuses card numbers, instructions, contact
 * details and banned statements); these checks only save a round trip and explain in plain words. */

import type { DialogState } from "@/lib/dialog-state";

/** What asking the drafter returns: the usual dialog state plus the draft it wrote, if any. */
export type DraftState = DialogState & {
  draft: { lines: string[]; words: number; reason: string } | null;
};

export const initialDraftState: DraftState = {
  attempt: 0,
  fieldErrors: {},
  error: null,
  draft: null,
};

export const MAX_SCRIPT_LINES = 12;
export const SCRIPT_LINE_MAX = 300;
/** About 150 spoken words a minute. */
export const WORDS_PER_SECOND = 2.5;

export const wordTarget = (lengthSeconds: number) =>
  Math.floor(lengthSeconds * WORDS_PER_SECOND);

/** Trimmed, non-empty lines of what was typed. */
export const splitLines = (text: string): string[] =>
  text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

export const countWords = (text: string): number =>
  text.split(/\s+/).filter(Boolean).length;

export type ScriptCheck =
  { ok: true; lines: string[] } | { ok: false; fieldErrors: { lines: string } };

export function checkScript(text: string, lengthSeconds: number): ScriptCheck {
  const lines = splitLines(text);
  const fail = (message: string): ScriptCheck => ({
    ok: false,
    fieldErrors: { lines: message },
  });
  if (lines.length === 0) return fail("Write at least a few words.");
  if (lines.length > MAX_SCRIPT_LINES)
    return fail(`A script has at most ${MAX_SCRIPT_LINES} lines.`);
  if (lines.some((line) => line.length > SCRIPT_LINE_MAX))
    return fail(`A line has at most ${SCRIPT_LINE_MAX} characters.`);
  const words = countWords(lines.join(" "));
  const target = wordTarget(lengthSeconds);
  if (words > target)
    return fail(
      `The script has ${words} words but ${lengthSeconds} seconds holds about ${target}.`,
    );
  return { ok: true, lines };
}

/** A plain sentence for each reason the API may refuse a script. */
export function scriptErrorText(
  code: string | null | undefined,
  fallback: string,
): string {
  switch (code) {
    case "script_empty":
      return "Write at least a few words.";
    case "script_too_many_lines":
      return `A script has at most ${MAX_SCRIPT_LINES} lines.`;
    case "script_line_too_long":
      return `A line has at most ${SCRIPT_LINE_MAX} characters.`;
    case "script_too_long":
      return fallback;
    case "script_unsafe_text":
      return "A line looks like a card number or an instruction. Take it out and write it in your own words.";
    case "script_contact_detail":
      return "A line holds a phone number or e-mail address. Never put those in a video.";
    case "script_banned_phrase":
      return "The script holds a statement that must never be made (see the never-say list on this page).";
    case "video_script_rate_limited":
      return "You have saved many scripts in the last hour. Try again later.";
    case "agent_unavailable":
      return "The video script drafter is switched off. An administrator can switch it on under AI agents.";
    case "agent_budget_reached":
      return "The video script drafter has used up its budget for this month.";
    case "video_draft_rate_limited":
      return "A script was drafted for this buyer a moment ago. Try again later.";
    case "video_draft_invalid_answer":
      return "The assistant's answer could not be used. Try again.";
    case "video_draft_unsupported_number":
      return "The draft held a number, amount or date that is not in the buyer's facts, so it was thrown away. Try again, or write it yourself.";
    case "video_draft_assumption_stated":
      return "The draft said a guess as if it were a fact, so it was thrown away. Try again, or write it yourself.";
    case "video_draft_script_banned_phrase":
      return "The draft held a statement that must never be made, so it was thrown away. Try again.";
    case "video_draft_script_contact_detail":
      return "The draft held a phone number or e-mail address, so it was thrown away. Try again.";
    case "video_draft_script_unsafe_text":
      return "The draft held text that looks like a card number or an instruction, so it was thrown away. Try again.";
    case "video_draft_script_too_long":
      return "The draft was longer than the chosen length, so it was thrown away. Try again or choose a longer video.";
    case "quote_not_found":
      return "That quote is not one of this buyer's quotes.";
    case "video_brief_quote_not_ready":
      return "Only an approved, sent or accepted quote can be used.";
    default:
      return fallback;
  }
}
