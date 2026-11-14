/**
 * Proposal decks of a quote (ADR 0032, PD4): the shape the API returns and the words the screens
 * use. The state, the file facts and who may do what all come from the API; nothing here decides.
 */

export type DeckState =
  "none" | "queued" | "ready" | "failed" | "not_available";

export type DeckStatus = {
  status: DeckState;
  reason: string | null;
  file_name: string | null;
  size_bytes: number | null;
  created_at: string | null;
  refresh_failed: boolean;
};

/** How often the card looks again while a deck is being made. */
export const DECK_REFRESH_MS = 4000;

export function deckStateText(status: DeckStatus): string {
  switch (status.status) {
    case "queued":
      return "The deck is being made. This page updates by itself.";
    case "ready":
      return status.refresh_failed
        ? "The last attempt to make a new deck failed. The earlier deck is still available."
        : "The deck is ready.";
    case "failed":
      return "The deck could not be made. Try again, and contact support if it keeps failing.";
    case "not_available":
      return (
        status.reason ??
        "A proposal deck is available once the quote is approved."
      );
    default:
      return "No deck yet.";
  }
}

export function isWorkingOnDeck(status: DeckStatus): boolean {
  return status.status === "queued";
}

/** The size in plain words ("84 KB"). */
export function deckSize(bytes: number | null): string {
  if (bytes === null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function deckErrorText(code: string | null, fallback: string): string {
  switch (code) {
    case "deck_pending":
      return "A deck for this quote is already being made. Wait a moment.";
    case "quote_not_ready_for_deck":
      return "A proposal deck is available once the quote is approved.";
    case "quote_superseded":
      return "This quote was replaced by a newer revision. Make the deck from the newest one.";
    case "deck_rate_limited":
      return "Too many decks were asked for. Try again later.";
    case "quote_not_found":
      return "That quote was not found.";
    case "forbidden":
      return "You may view this quote but not change it, so you cannot make a deck for it.";
    default:
      return fallback;
  }
}
