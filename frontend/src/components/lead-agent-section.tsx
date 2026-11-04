import { askLeadAgent } from "@/app/(app)/lead-agent/actions";
import { AskLeadAgentButton } from "@/components/lead-agent-card";
import { Card } from "@/components/ui";
import type { Me } from "@/lib/api-types";
import { canRunQualifier } from "@/lib/permissions";

/**
 * The lead agent on a lead page (ADR 0022): one card with the "Ask the lead agent" button. Like
 * the other extra cards it is information - the page works without it. The same people who may
 * run the Qualifier may ask it; the API decides again (and says when it is switched off).
 */
export function LeadAgentSection({
  me,
  leadId,
}: {
  me: Pick<Me, "permissions">;
  leadId: string;
}) {
  if (!canRunQualifier(me)) return null;
  return (
    <Card id="lead-agent" aria-labelledby="lead-agent-heading" className="p-5">
      <h2
        id="lead-agent-heading"
        className="text-base font-semibold text-slate-900"
      >
        Lead agent
      </h2>
      <div className="mt-3">
        <AskLeadAgentButton action={askLeadAgent.bind(null, leadId)} />
      </div>
    </Card>
  );
}
