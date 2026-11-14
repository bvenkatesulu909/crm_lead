import { createProposalDeck } from "@/app/(app)/quotes/deck-actions";
import { StaffDeck } from "@/components/deck-views";
import { Card } from "@/components/ui";
import {
  deckQuery,
  type DeckFormat,
  type DeckStatus,
} from "@/lib/proposal-decks";
import { apiFetch } from "@/lib/server/api";

const SECTIONS: { format: DeckFormat; title: string; href: string }[] = [
  { format: "pdf", title: "PDF", href: "deck" },
  { format: "pptx", title: "PowerPoint (editable)", href: "deck?format=pptx" },
];

/**
 * The proposal deck of one quote (ADR 0032): a PDF and a PowerPoint file, each with its own state,
 * download and button. Information and buttons only: the quote page works without it, and the API
 * answers 404 when the person may not read the quote (then nothing shows).
 */
export async function DeckCard({
  quoteId,
  canCreate,
}: {
  quoteId: string;
  canCreate: boolean;
}) {
  const decks = await Promise.all(
    SECTIONS.map(({ format }) =>
      apiFetch<DeckStatus>(`/quotes/${quoteId}/deck${deckQuery(format)}`).catch(
        () => null,
      ),
    ),
  );
  if (!decks[0]) return null;
  return (
    <Card id="deck" aria-labelledby="deck-heading">
      <h2
        id="deck-heading"
        className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900"
      >
        Proposal deck
      </h2>
      <div className="space-y-5 px-5 py-4">
        {SECTIONS.map(({ format, title, href }, index) => {
          const deck = decks[index];
          if (!deck) return null;
          return (
            <section key={format} aria-label={title} className="space-y-2">
              <h3 className="text-sm font-semibold text-slate-800">{title}</h3>
              <StaffDeck
                deck={deck}
                downloadHref={`/quotes/${quoteId}/${href}`}
                canCreate={canCreate}
                action={createProposalDeck.bind(null, quoteId, format)}
                format={format}
                showNote={format === "pdf"}
              />
            </section>
          );
        })}
      </div>
    </Card>
  );
}
