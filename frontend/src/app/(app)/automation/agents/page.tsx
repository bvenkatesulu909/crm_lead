import type { Metadata } from "next";

import { AgentSettingsForm } from "@/components/agent-settings-form";
import { AgentCard } from "@/components/agent-views";
import { Forbidden, PageHeader, SuccessAlert } from "@/components/ui";
import type { AgentPage } from "@/lib/api-types";
import { canManageAgents, canReadAgents } from "@/lib/permissions";
import { initialFormState } from "@/lib/form-state";
import { apiFetch, getMe } from "@/lib/server/api";

import { updateAgent } from "./actions";

export const metadata: Metadata = { title: "AI agents" };

/**
 * The CRM's AI agents (ADR 0016): which exist, whether they are on, how much of the month's
 * token budget they used and which tools they may use. Tenant admins change them; sales
 * managers only read.
 */
export default async function AgentsPage({
  searchParams,
}: PageProps<"/automation/agents">) {
  const query = await searchParams;
  const me = await getMe();
  if (!canReadAgents(me)) return <Forbidden />;
  const { items } = await apiFetch<AgentPage>("/agents");
  const canChange = canManageAgents(me);
  const saved = items.find((a) => a.key === query.done);

  return (
    <>
      {saved && (
        <div className="mb-4">
          <SuccessAlert>
            The settings of {saved.title.toLowerCase()} were saved.
          </SuccessAlert>
        </div>
      )}
      <PageHeader
        title="AI agents"
        description="The CRM's AI features. Switch one off, limit how much it may use each month, or take away tools. A change applies from the agent's next question."
      />
      <div className="space-y-6">
        {items.map((agent) => (
          <AgentCard key={agent.key} agent={agent}>
            {canChange && (
              <AgentSettingsForm
                agent={agent}
                initialState={initialFormState}
                action={updateAgent.bind(
                  null,
                  agent.key,
                  agent.version,
                  agent.all_tools,
                )}
              />
            )}
          </AgentCard>
        ))}
      </div>
      {!canChange && (
        <p className="mt-6 text-sm text-slate-600">
          Only a tenant administrator can change these settings.
        </p>
      )}
    </>
  );
}
