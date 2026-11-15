/**
 * Buyer memory on the lead page (ADR 0028): the words and the checks shared by the card and its
 * Server Actions. The API decides everything that matters (the tenant, the lead, the rules); these
 * checks only save a round trip and explain a refusal in plain words.
 */
import type { BuyerMemory, BuyerMemoryItem } from "@/lib/api-types";
import { isUuid } from "@/lib/communications";

/** The most characters of a value, a quote or a reason (the API cleans first, then checks). */
export const MEMORY_TEXT_MAX = 300;

/** Where a fact came from, in words (only the first is offered by the form; the rest are set by code). */
export const MEMORY_SOURCE_LABELS: Record<string, string> = {
  buyer_confirmed: "Buyer confirmed",
  timeline_entry: "A note on this lead's timeline",
  lead_record: "The lead form",
  website_chat: "The website chat",
};

export const sourceLabel = (source: string | null) =>
  source ? (MEMORY_SOURCE_LABELS[source] ?? "Another source") : "";

/** What the card says about the three groups, e.g. "2 facts · 1 assumption · 9 still to ask". */
export function memorySummary(data: BuyerMemory): string {
  const facts = data.current.filter((i) => i.status === "fact").length;
  const guesses = data.current.length - facts;
  const plural = (n: number, one: string, many: string) =>
    `${n} ${n === 1 ? one : many}`;
  return [
    plural(facts, "fact", "facts"),
    plural(guesses, "assumption", "assumptions"),
    `${data.gaps.length} still to ask`,
  ].join(" · ");
}

export type MemoryGroups = {
  facts: BuyerMemoryItem[];
  assumptions: BuyerMemoryItem[];
};

export function groupMemory(data: BuyerMemory): MemoryGroups {
  return {
    facts: data.current.filter((i) => i.status === "fact"),
    assumptions: data.current.filter((i) => i.status === "assumption"),
  };
}

/** Plain words for the API's refusals. */
export function memoryErrorText(code: string | null, fallback: string): string {
  switch (code) {
    case "memory_value_refused":
      return "That text was refused: it looks like a card number or an instruction to an AI. Please write it in your own words.";
    case "memory_invalid":
      return fallback;
    case "memory_source_not_found":
      return "That note does not belong to this lead.";
    case "memory_full":
      return "This lead already holds as much buyer memory as the CRM keeps. Ask an administrator.";
    case "memory_not_an_assumption":
      return "Only an assumption can be confirmed.";
    case "memory_not_current":
      return "A newer entry exists for this detail. Reload the page and confirm that one instead.";
    case "lead_not_found":
    case "memory_item_not_found":
      return "This lead or entry could not be found. It may have been changed; reload the page.";
    default:
      return fallback;
  }
}

export type NewMemoryInput = {
  key: string;
  status: string;
  value: string;
  quote: string;
  reason: string;
};

export type Checked<T> =
  { ok: true; body: T } | { ok: false; fieldErrors: Record<string, string> };

const tooLong = (name: string, text: string) =>
  text.length > MEMORY_TEXT_MAX
    ? `${name} is too long (at most ${MEMORY_TEXT_MAX} characters).`
    : null;

/**
 * The body of a new entry. A fact is always sent as "the buyer confirmed" with the quote (the only
 * source the form offers); an assumption with its reason. Nothing else is ever sent.
 */
export function checkNewMemory(
  input: NewMemoryInput,
  keys: readonly string[],
): Checked<Record<string, string>> {
  const fieldErrors: Record<string, string> = {};
  const value = input.value.trim();
  const quote = input.quote.trim();
  const reason = input.reason.trim();
  if (!keys.includes(input.key)) fieldErrors.key = "Choose what this is about.";
  if (input.status !== "fact" && input.status !== "assumption")
    fieldErrors.status = "Say whether the buyer told us or we think so.";
  if (!value) fieldErrors.value = "Write the detail.";
  else if (tooLong("The detail", value))
    fieldErrors.value = tooLong("The detail", value)!;
  if (input.status === "fact") {
    if (!quote) fieldErrors.quote = "Write what the buyer said.";
    else if (tooLong("The quote", quote))
      fieldErrors.quote = tooLong("The quote", quote)!;
  } else if (input.status === "assumption") {
    if (!reason) fieldErrors.reason = "Say why we think so.";
    else if (tooLong("The reason", reason))
      fieldErrors.reason = tooLong("The reason", reason)!;
  }
  if (Object.keys(fieldErrors).length) return { ok: false, fieldErrors };
  return input.status === "fact"
    ? {
        ok: true,
        body: {
          key: input.key,
          value,
          status: "fact",
          source: "buyer_confirmed",
          quote,
        },
      }
    : {
        ok: true,
        body: { key: input.key, value, status: "assumption", reason },
      };
}

/** The body for confirming an assumption: the buyer's words, and optionally a corrected value. */
export function checkConfirm(input: {
  itemId: string;
  quote: string;
  value: string;
}): Checked<{ itemId: string; body: Record<string, string> }> {
  const fieldErrors: Record<string, string> = {};
  const quote = input.quote.trim();
  const value = input.value.trim();
  if (!isUuid(input.itemId))
    fieldErrors.item_id = "Choose an entry to confirm.";
  if (!quote) fieldErrors.quote = "Write what the buyer said.";
  else if (tooLong("The quote", quote))
    fieldErrors.quote = tooLong("The quote", quote)!;
  if (value && tooLong("The detail", value))
    fieldErrors.value = tooLong("The detail", value)!;
  if (Object.keys(fieldErrors).length) return { ok: false, fieldErrors };
  const body: Record<string, string> = { source: "buyer_confirmed", quote };
  if (value) body.value = value;
  return { ok: true, body: { itemId: input.itemId, body } };
}
