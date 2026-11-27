/** Words and checks for writing and saving a buyer-video script (ADR 0041, VB3). The API decides
 * everything that matters (it cleans the text and refuses card numbers, instructions, contact
 * details and banned statements); these checks only save a round trip and explain in plain words. */

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
    default:
      return fallback;
  }
}
