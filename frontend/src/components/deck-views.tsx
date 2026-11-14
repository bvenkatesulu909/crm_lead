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
  type DeckFormat,
  type DeckStatus,
} from "@/lib/proposal-decks";

type CreateAction = (state: DialogState) => Promise<DialogState>;

/** The words of each format. The PDF keeps the wording it always had. */
const WORDS: Record<
  DeckFormat,
  { testId: string; download: string; create: string; renew: string }
> = {
  pdf: {
    testId: "deck-state",
    download: "Download deck",
    create: "Create proposal deck",
    renew: "Make a new deck",
  },
  pptx: {
    testId: "deck-state-pptx",
    download: "Download PowerPoint",
    create: "Create PowerPoint",
    renew: "Make a new PowerPoint",
  },
};

/**
 * The staff view of a quote's proposal deck: where it stands, the download (a plain link to a route
 * handler, so no token reaches the browser) and a button to make a new one. While a deck is being
 * made the card looks again every few seconds. One block per format (PDF or PowerPoint).
 */
export function StaffDeck({
  deck,
  downloadHref,
  canCreate,
  action,
  format = "pdf",
  showNote = true,
  refreshMs = DECK_REFRESH_MS,
}: {
  deck: DeckStatus;
  downloadHref: string;
  canCreate: boolean;
  action: CreateAction;
  format?: DeckFormat;
  /** The branding note is shown once per card: the second block leaves it out. */
  showNote?: boolean;
  refreshMs?: number;
}) {
  const words = WORDS[format];
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
        data-testid={words.testId}
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
            {words.download}
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
                  ? words.renew
                  : words.create}
            </button>
          </form>
        )}
      </div>
      {!unavailable && showNote && (
        <p className="text-xs text-slate-500">
          Uses your organisation&apos;s branding. A new deck is only needed when
          the branding changes.
        </p>
      )}
    </div>
  );
}

/**
 * The "why this proposal" slide of a quote's deck (ADR 0032 Amendment A, PD7): the approved text, as
 * plain text, and a button that asks the deck writer for a draft. A draft is only a proposal: a
 * different person approves it in the approval queue, and only an approved text is drawn into the
 * next deck.
 */
export function SummaryBlock({
  summary,
  canDraft,
  action,
}: {
  summary: string | null;
  canDraft: boolean;
  action: CreateAction;
}) {
  const [state, formAction, pending] = useActionState(
    action,
    initialDialogState,
  );
  return (
    <div className="space-y-3">
      {state.error && (
        <ErrorAlert title="The draft could not be made" error={state.error} />
      )}
      <p
        data-testid="deck-summary"
        className="whitespace-pre-line text-sm text-slate-700"
      >
        {summary ?? "No summary slide yet."}
      </p>
      {canDraft && (
        <form action={formAction}>
          <button
            type="submit"
            disabled={pending}
            className={buttonClass(summary ? "secondary" : "primary")}
          >
            {pending
              ? "Drafting…"
              : summary
                ? "Draft a new one"
                : "Draft with the deck writer"}
          </button>
        </form>
      )}
      <p className="text-xs text-slate-500">
        The draft goes to the approval queue and a different person approves it.
        Only approved text is drawn into the next deck.
      </p>
    </div>
  );
}
