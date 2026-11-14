"use client";

import { useRouter } from "next/navigation";
import { useActionState, useEffect } from "react";

import { ErrorAlert, buttonClass } from "@/components/ui";
import { initialDialogState, type DialogState } from "@/lib/dialog-state";
import { formatDateTime } from "@/lib/format";
import {
  DECK_REFRESH_MS,
  deckSize,
  deckStateText,
  isWorkingOnDeck,
  type DeckStatus,
} from "@/lib/proposal-decks";

type CreateAction = (state: DialogState) => Promise<DialogState>;

/**
 * The staff view of a quote's proposal deck: where it stands, the download (a plain link to a route
 * handler, so no token reaches the browser) and a button to make a new one. While a deck is being
 * made the card looks again every few seconds.
 */
export function StaffDeck({
  deck,
  downloadHref,
  canCreate,
  action,
  refreshMs = DECK_REFRESH_MS,
}: {
  deck: DeckStatus;
  downloadHref: string;
  canCreate: boolean;
  action: CreateAction;
  refreshMs?: number;
}) {
  const router = useRouter();
  const [state, formAction, pending] = useActionState(
    action,
    initialDialogState,
  );
  const working = isWorkingOnDeck(deck);

  useEffect(() => {
    if (!working) return;
    const timer = setInterval(() => router.refresh(), refreshMs);
    return () => clearInterval(timer);
  }, [working, router, refreshMs]);

  const unavailable = deck.status === "not_available";
  return (
    <div className="space-y-3">
      {state.error && (
        <ErrorAlert title="The deck could not be made" error={state.error} />
      )}
      <p
        data-testid="deck-state"
        className="text-sm text-slate-700"
        role={working ? "status" : undefined}
      >
        {deckStateText(deck)}
      </p>
      {deck.status === "ready" && deck.file_name && (
        <p className="text-xs text-slate-500">
          {deck.file_name}
          {deck.size_bytes !== null && ` · ${deckSize(deck.size_bytes)}`}
          {deck.created_at && ` · made ${formatDateTime(deck.created_at)}`}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        {deck.status === "ready" && (
          <a href={downloadHref} download className={buttonClass("primary")}>
            Download deck
          </a>
        )}
        {canCreate && !unavailable && (
          <form action={formAction}>
            <button
              type="submit"
              disabled={pending || working}
              className={buttonClass(
                deck.status === "ready" ? "secondary" : "primary",
              )}
            >
              {pending || working
                ? "Making…"
                : deck.status === "ready"
                  ? "Make a new deck"
                  : "Create proposal deck"}
            </button>
          </form>
        )}
      </div>
      {!unavailable && (
        <p className="text-xs text-slate-500">
          Uses your organisation&apos;s branding. A new deck is only needed when
          the branding changes.
        </p>
      )}
    </div>
  );
}
