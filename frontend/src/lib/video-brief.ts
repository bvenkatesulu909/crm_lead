/** Words and choices for the video brief (ADR 0041). The lists are fixed: the API checks them again. */
import type { QuoteSummary, VideoBrief } from "@/lib/api-types";
import { LANGUAGE_LABELS } from "@/lib/format";

export const GOAL_LABELS = {
  introduce: "Introduce ourselves",
  follow_up: "Follow up after a call",
  after_visit: "After a site visit",
  explain_quote: "Explain a quote",
  revive: "Revive a quiet lead",
} as const;
export type Goal = keyof typeof GOAL_LABELS;

export const TONE_LABELS = {
  warm: "Warm",
  professional: "Professional",
  brisk: "Brisk",
} as const;
export type Tone = keyof typeof TONE_LABELS;

export const LENGTHS = [30, 60, 90] as const;
export type Length = (typeof LENGTHS)[number];

export type Language = "en" | "hi" | "te";
export const LANGUAGES: Language[] = ["en", "hi", "te"];

/** What the person chose on the page. A blank language means "the buyer's own". */
export type Choices = {
  goal: Goal;
  language: Language | "";
  tone: Tone;
  length: Length;
  quoteId: string;
};

export const DEFAULT_CHOICES: Choices = {
  goal: "follow_up",
  language: "",
  tone: "warm",
  length: 60,
  quoteId: "",
};

const first = (v: string | string[] | undefined) =>
  (Array.isArray(v) ? v[0] : v)?.trim() ?? "";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Reads the choices from the page address; anything outside the fixed lists falls back to the
 * default, so a changed address can never send the API something odd. */
export function parseChoices(
  params: Record<string, string | string[] | undefined>,
): Choices {
  const goal = first(params.goal);
  const language = first(params.language);
  const tone = first(params.tone);
  const length = Number(first(params.length));
  const quote = first(params.quote_id);
  return {
    goal: goal in GOAL_LABELS ? (goal as Goal) : DEFAULT_CHOICES.goal,
    language: (LANGUAGES as string[]).includes(language)
      ? (language as Language)
      : "",
    tone: tone in TONE_LABELS ? (tone as Tone) : DEFAULT_CHOICES.tone,
    length: (LENGTHS as readonly number[]).includes(length)
      ? (length as Length)
      : DEFAULT_CHOICES.length,
    quoteId: UUID.test(quote) ? quote : "",
  };
}

/** The API path for the chosen brief. */
export function briefPath(leadId: string, c: Choices): string {
  const q = new URLSearchParams({
    goal: c.goal,
    tone: c.tone,
    length: String(c.length),
  });
  if (c.language) q.set("language", c.language);
  if (c.quoteId) q.set("quote_id", c.quoteId);
  return `/leads/${leadId}/video-brief?${q.toString()}`;
}

/** Quotes whose prices may be spoken (the API checks again and the lead's account decides). */
export const PRICE_QUOTE_STATUSES = ["approved", "sent", "accepted"] as const;

export const quotesPath = (accountId: string) =>
  `/quotes?account_id=${accountId}&${PRICE_QUOTE_STATUSES.map((s) => `status=${s}`).join("&")}&limit=50`;

export const quoteOptionLabel = (
  q: Pick<QuoteSummary, "number" | "revision" | "title" | "status">,
) =>
  `QT-${String(q.number).padStart(4, "0")}${q.revision > 1 ? ` rev ${q.revision}` : ""}: ${q.title} (${q.status})`;

export const languageName = (code: string) => LANGUAGE_LABELS[code] ?? code;

type Kind = VideoBrief["known"][number]["kind"];

/** The badge on a "what it is built from" line. */
export const knownBadge = (kind: Kind) =>
  ({
    fact: "Fact",
    assumption: "Assumption",
    form: "Lead form",
    price: "Quote",
  })[kind];

/** What happens to that line in the script. */
export const knownNote = (kind: Kind) =>
  ({
    fact: "May be said as a statement.",
    assumption: "Only asked as a question - never said as a fact.",
    form: "Shown only: the buyer has not confirmed it, so it is not said.",
    price: "Said exactly as the quote shows it.",
  })[kind];

type ScriptKind = VideoBrief["script"][number]["kind"];

export const scriptBadge = (kind: ScriptKind) =>
  ({
    greeting: "Greeting",
    intro: "Intro",
    fact: "Fact",
    price: "Price",
    question: "Question",
    closing: "Closing",
  })[kind];

/** A plain sentence for each reason the API may refuse a quote. */
export function quoteProblemText(
  code: string | null | undefined,
): string | null {
  if (code === "quote_not_found")
    return "That quote is not one of this buyer's quotes, so no prices were added.";
  if (code === "video_brief_quote_not_ready")
    return "Only an approved, sent or accepted quote can be used, so no prices were added.";
  return null;
}

/** The choices exactly as sent by a form, or null when anything is outside the fixed lists or no
 * language was given (a script is always for one language). Unlike `parseChoices`, which falls
 * back to defaults for a page address, a form that was changed is refused. */
export function strictChoices(raw: Record<string, string>): Choices | null {
  const parsed = parseChoices(raw);
  const same =
    parsed.goal === raw.goal &&
    parsed.language !== "" &&
    parsed.language === raw.language &&
    parsed.tone === raw.tone &&
    String(parsed.length) === raw.length;
  return same ? parsed : null;
}
