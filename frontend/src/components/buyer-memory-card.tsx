import {
  addMemory,
  confirmMemory,
  copyMemoryFromLead,
} from "@/app/(app)/leads/[id]/memory-actions";
import { BuyerMemoryView } from "@/components/buyer-memory-views";
import { Card } from "@/components/ui";
import type { BuyerMemory, Me } from "@/lib/api-types";
import { canReadBuyerMemory, canWriteBuyerMemory } from "@/lib/permissions";
import { apiFetch } from "@/lib/server/api";

/**
 * What we know about this buyer (ADR 0028): facts, assumptions and what is still to ask. Information
 * only - the lead page works without it - and the API answers 404 when the person may not read the
 * lead, then nothing is shown.
 */
export async function BuyerMemoryCard({
  me,
  leadId,
}: {
  me: Pick<Me, "permissions">;
  leadId: string;
}) {
  if (!canReadBuyerMemory(me)) return null;
  const data = await apiFetch<BuyerMemory>(`/leads/${leadId}/memory`).catch(
    () => null,
  );
  if (!data) return null;
  return (
    <Card
      id="buyer-memory"
      aria-labelledby="buyer-memory-heading"
      className="p-5"
    >
      <h2
        id="buyer-memory-heading"
        className="text-base font-semibold text-slate-900"
      >
        Buyer memory
      </h2>
      <div className="mt-3">
        <BuyerMemoryView
          data={data}
          canWrite={canWriteBuyerMemory(me)}
          addAction={addMemory.bind(null, leadId)}
          confirmAction={confirmMemory.bind(null, leadId)}
          copyAction={copyMemoryFromLead.bind(null, leadId)}
        />
      </div>
    </Card>
  );
}
