import { runCustomAgent } from "@/app/(app)/custom-agents/actions";
import { RunCustomAgentButton } from "@/components/run-custom-agent";
import { Card } from "@/components/ui";
import type {
  CustomAgentPage,
  CustomAgentRecordType,
  Me,
} from "@/lib/api-types";
import { isRunnable } from "@/lib/custom-agents";
import { canRunCustomAgents } from "@/lib/permissions";
import { apiFetch } from "@/lib/server/api";

/**
 * The organisation's custom agents on a record's page (ADR 0034): one button per agent that is
 * switched on, has had a dry run of its current version and works on this kind of record. Like the
 * other extra cards it is information - the page works without it, and it shows nothing when
 * there is nothing to run. The agents only suggest; a different person approves. The API decides
 * again who may run what, and on which record.
 */
export async function CustomAgentsSection({
  me,
  recordType,
  recordId,
}: {
  me: Pick<Me, "permissions">;
  recordType: CustomAgentRecordType;
  recordId: string;
}) {
  if (!canRunCustomAgents(me)) return null;
  const page = await apiFetch<CustomAgentPage>("/custom-agents").catch(
    () => null,
  );
  const agents = (page?.items ?? []).filter(
    (agent) => agent.record_type === recordType && isRunnable(agent),
  );
  if (agents.length === 0) return null;
  return (
    <Card
      id="custom-agents"
      aria-labelledby="custom-agents-heading"
      className="p-5"
    >
      <h2
        id="custom-agents-heading"
        className="text-base font-semibold text-slate-900"
      >
        Custom agents
      </h2>
      <p className="mt-1 text-xs text-slate-500">
        Each agent reads this record and may suggest a change. Nothing changes
        until a different person approves it.
      </p>
      <div className="mt-3 space-y-4">
        {agents.map((agent) => (
          <RunCustomAgentButton
            key={agent.id}
            name={agent.name}
            purpose={agent.purpose}
            action={runCustomAgent.bind(null, agent.id, recordId)}
          />
        ))}
      </div>
    </Card>
  );
}
