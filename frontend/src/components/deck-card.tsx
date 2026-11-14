import { createProposalDeck } from "@/app/(app)/quotes/deck-actions";
import { StaffDeck } from "@/components/deck-views";
import { Card } from "@/components/ui";
import type { DeckStatus } from "@/lib/proposal-decks";
import { apiFetch } from "@/lib/server/api";

/**
 * The proposal deck of one quote (ADR 0032). Information and one button: the quote page works
 * without it, and the API answers 404 when the person may not read the quote (then nothing shows).
 */
export async function DeckCard({
  quoteId,
  canCreate,
}: {
  quoteId: string;
  canCreate: boolean;
}) {
  const deck = await apiFetch<DeckStatus>(`/quotes/${quoteId}/deck`).catch(
    () => null,
  );
  if (!deck) return null;
  return (
    <Card id="deck" aria-labelledby="deck-heading">
      <h2
        id="deck-heading"
        className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900"
      >
        Proposal deck
      </h2>
      <div className="px-5 py-4">
        <StaffDeck
          deck={deck}
          downloadHref={`/quotes/${quoteId}/deck`}
          canCreate={canCreate}
          action={createProposalDeck.bind(null, quoteId)}
        />
      </div>
    </Card>
  );
}
