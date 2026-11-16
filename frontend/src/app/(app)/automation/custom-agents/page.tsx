import type { Metadata } from "next";
import Link from "next/link";

import {
  ButtonLink,
  Card,
  EmptyState,
  Forbidden,
  PageHeader,
  SuccessAlert,
  cx,
} from "@/components/ui";
import type { CustomAgentPage } from "@/lib/api-types";
import { agentState, recordNoun } from "@/lib/custom-agents";
import { canManageCustomAgents } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

export const metadata: Metadata = { title: "Custom agents" };

const DONE: Record<string, string> = {
  archived: "The agent was retired.",
};
const TONE = {
  good: "bg-emerald-50 text-emerald-800",
  wait: "bg-amber-50 text-amber-800",
  off: "bg-slate-100 text-slate-600",
} as const;

/**
 * Custom agents (ADR 0034): small AI helpers an administrator defines from fixed menus, tries on a
 * real record and switches on. Sales staff run them from a record's page. They only ever suggest:
 * a different person approves every suggestion in the approval queue.
 */
export default async function CustomAgentsPage({
  searchParams,
}: PageProps<"/automation/custom-agents">) {
  const query = await searchParams;
  const me = await getMe();
  if (!canManageCustomAgents(me)) return <Forbidden />;
  const page = await apiFetch<CustomAgentPage>("/custom-agents");
  const done = typeof query.done === "string" ? DONE[query.done] : undefined;
  const full = page.items.length >= page.max_agents;
  return (
    <>
      {done && (
        <div className="mb-4">
          <SuccessAlert>{done}</SuccessAlert>
        </div>
      )}
      <PageHeader
        title="Custom agents"
        description="Small AI helpers you define for your team. An agent reads one record and may suggest a follow-up task or a status change; it can never change anything itself. A different person approves every suggestion."
        actions={
          full ? undefined : (
            <ButtonLink href="/automation/custom-agents/new">
              New custom agent
            </ButtonLink>
          )
        }
      />
      {page.items.length === 0 ? (
        <EmptyState
          title="No custom agents yet"
          description="Define one, try it on a real record, then switch it on. Your sales team then sees a Run button on that kind of record."
        />
      ) : (
        <ul className="space-y-3">
          {page.items.map((agent) => {
            const state = agentState(agent);
            return (
              <li key={agent.id}>
                <Card className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
                  <div>
                    <h2 className="text-base font-semibold text-slate-900">
                      <Link
                        href={`/automation/custom-agents/${agent.id}`}
                        className="hover:underline"
                      >
                        {agent.name}
                      </Link>
                    </h2>
                    <p className="text-sm text-slate-600">{agent.purpose}</p>
                    <p className="mt-1 text-xs text-slate-500">
                      Works on {recordNoun(agent.record_type)} · version{" "}
                      {agent.current_version}
                    </p>
                  </div>
                  <span
                    className={cx(
                      "rounded px-2 py-1 text-xs font-medium",
                      TONE[state.tone],
                    )}
                  >
                    {state.label}
                  </span>
                </Card>
              </li>
            );
          })}
        </ul>
      )}
      {full && (
        <p className="mt-4 text-sm text-slate-600">
          An organisation can have at most {page.max_agents} custom agents.
          Retire one to make room.
        </p>
      )}
    </>
  );
}
