import type { Metadata } from "next";
import { notFound } from "next/navigation";

import {
  archiveCustomAgent,
  switchCustomAgent,
  tryCustomAgent,
  updateCustomAgent,
} from "@/app/(app)/custom-agents/actions";
import { CustomAgentForm } from "@/components/custom-agent-form";
import {
  RetireCustomAgent,
  SwitchCustomAgent,
} from "@/components/custom-agent-controls";
import {
  CustomAgentTry,
  type RecordChoice,
} from "@/components/custom-agent-try";
import { Card, Forbidden, PageHeader, SuccessAlert, cx } from "@/components/ui";
import { ApiError } from "@/lib/api-error";
import type {
  AccountPage,
  Agent,
  CustomAgent,
  CustomAgentMenus,
  CustomAgentRunPage,
  CustomAgentVersion,
  LeadPage,
  OpportunityPage,
} from "@/lib/api-types";
import { isUuid } from "@/lib/communications";
import {
  ACTION_TEXT,
  RECORD_TYPE_LABELS,
  agentState,
  initialTrialState,
  recordNoun,
} from "@/lib/custom-agents";
import { formatDateTime } from "@/lib/format";
import { initialFormState } from "@/lib/form-state";
import { canManageCustomAgents } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

export const metadata: Metadata = { title: "Custom agent" };

const DONE: Record<string, string> = {
  created:
    "The agent was created. It is switched off: try it on a real record, then switch it on.",
  saved:
    "Saved as a new version. It needs a new dry run before it can be switched on or run.",
  on: "The agent is switched on. Sales staff now see a Run button on that kind of record.",
  off: "The agent is switched off.",
};
const TONE = {
  good: "bg-emerald-50 text-emerald-800",
  wait: "bg-amber-50 text-amber-800",
  off: "bg-slate-100 text-slate-600",
} as const;

async function choicesFor(agent: CustomAgent): Promise<RecordChoice[]> {
  if (agent.record_type === "lead") {
    const page = await apiFetch<LeadPage>("/leads?limit=50").catch(() => null);
    return (page?.items ?? []).map((lead) => ({
      id: lead.id,
      label: [
        [lead.first_name, lead.last_name].filter(Boolean).join(" "),
        lead.company_name,
      ]
        .filter(Boolean)
        .join(" - "),
    }));
  }
  if (agent.record_type === "account") {
    const page = await apiFetch<AccountPage>("/accounts?limit=50").catch(
      () => null,
    );
    return (page?.items ?? []).map((a) => ({ id: a.id, label: a.name }));
  }
  const page = await apiFetch<OpportunityPage>("/opportunities?limit=50").catch(
    () => null,
  );
  return (page?.items ?? []).map((o) => ({ id: o.id, label: o.name }));
}

/** One custom agent (ADR 0034): its definition, the dry run, the switch, its versions and runs. */
export default async function CustomAgentPage({
  params,
  searchParams,
}: PageProps<"/automation/custom-agents/[id]">) {
  const { id } = await params;
  const query = await searchParams;
  const me = await getMe();
  if (!canManageCustomAgents(me)) return <Forbidden />;
  if (!isUuid(id)) notFound();

  let agent: CustomAgent;
  try {
    agent = await apiFetch<CustomAgent>(`/custom-agents/${id}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
  const [menus, versions, runs, registry, choices] = await Promise.all([
    apiFetch<CustomAgentMenus>("/custom-agents/menus"),
    apiFetch<CustomAgentVersion[]>(`/custom-agents/${id}/versions`),
    apiFetch<CustomAgentRunPage>(`/custom-agents/${id}/runs?limit=10`),
    apiFetch<Agent>(`/agents/${agent.agent_key}`).catch(() => null),
    choicesFor(agent),
  ]);
  const state = agentState(agent);
  const done = typeof query.done === "string" ? DONE[query.done] : undefined;
  const registryVersion = registry?.version ?? null;

  return (
    <>
      {done && (
        <div className="mb-4">
          <SuccessAlert>{done}</SuccessAlert>
        </div>
      )}
      <PageHeader
        title={agent.name}
        description={`${agent.purpose} Works on ${recordNoun(agent.record_type)}.`}
        actions={
          <span
            className={cx(
              "rounded px-2 py-1 text-xs font-medium",
              TONE[state.tone],
            )}
          >
            {state.label}
          </span>
        }
      />
      <div className="space-y-6">
        <Card className="p-5" aria-labelledby="try-heading">
          <h2
            id="try-heading"
            className="text-base font-semibold text-slate-900"
          >
            Dry run and switch
          </h2>
          <p className="mt-1 text-sm text-slate-600">
            Pick one real record and see what version {agent.current_version}{" "}
            would suggest. Nothing is proposed or changed. Once a version has
            had a dry run, you can switch the agent on.
          </p>
          <div className="mt-4">
            <CustomAgentTry
              recordLabel={RECORD_TYPE_LABELS[agent.record_type]}
              choices={choices}
              initialState={initialTrialState}
              action={tryCustomAgent.bind(null, agent.id)}
            />
          </div>
          <div className="mt-5 border-t border-slate-100 pt-4">
            <SwitchCustomAgent
              enabled={agent.enabled}
              tried={agent.tried}
              onAction={switchCustomAgent.bind(
                null,
                agent.id,
                agent.agent_key,
                registryVersion,
                true,
              )}
              offAction={switchCustomAgent.bind(
                null,
                agent.id,
                agent.agent_key,
                registryVersion,
                false,
              )}
            />
            {registry && (
              <p className="mt-2 text-xs text-slate-500">
                This month: {registry.used_tokens.toLocaleString("en-IN")} of{" "}
                {registry.monthly_token_budget.toLocaleString("en-IN")} tokens
                used. The budget is set on the AI agents page.
              </p>
            )}
          </div>
        </Card>

        <Card className="p-5" aria-labelledby="definition-heading">
          <h2
            id="definition-heading"
            className="text-base font-semibold text-slate-900"
          >
            Definition
          </h2>
          <div className="mt-4">
            <CustomAgentForm
              menus={menus}
              initial={{
                name: agent.name,
                purpose: agent.purpose,
                instruction: agent.instruction ?? "",
                read_sets: agent.read_sets,
                suggestion_kinds: agent.suggestion_kinds,
              }}
              initialState={initialFormState}
              action={updateCustomAgent.bind(null, agent.id, agent.version)}
              submitLabel="Save as a new version"
            />
          </div>
        </Card>

        <Card className="p-5" aria-labelledby="versions-heading">
          <h2
            id="versions-heading"
            className="text-base font-semibold text-slate-900"
          >
            Versions
          </h2>
          <ul className="mt-3 space-y-1 text-sm text-slate-700">
            {versions.map((v) => (
              <li key={v.version_no}>
                Version {v.version_no}
                {v.version_no === agent.current_version && " (current)"} ·{" "}
                {formatDateTime(v.created_at)}
                {v.cleaned.length > 0 && (
                  <span className="text-slate-500">
                    {" "}
                    · cleaned: {v.cleaned.join(", ")}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </Card>

        <Card className="p-5" aria-labelledby="runs-heading">
          <h2
            id="runs-heading"
            className="text-base font-semibold text-slate-900"
          >
            Recent runs
          </h2>
          {runs.items.length === 0 ? (
            <p className="mt-2 text-sm text-slate-600">Nothing has run yet.</p>
          ) : (
            <ul className="mt-3 space-y-1 text-sm text-slate-700">
              {runs.items.map((run) => (
                <li key={run.id}>
                  {run.mode === "trial" ? "Dry run" : "Run"} of version{" "}
                  {run.version_no} · {ACTION_TEXT[run.action] ?? run.action} ·{" "}
                  {run.outcome.replace("_", " ")} ·{" "}
                  {formatDateTime(run.created_at)}
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="p-5" aria-labelledby="retire-heading">
          <h2
            id="retire-heading"
            className="text-base font-semibold text-slate-900"
          >
            Retire
          </h2>
          <p className="mt-1 text-sm text-slate-600">
            A retired agent can no longer be run or edited. Its history stays.
          </p>
          <div className="mt-3">
            <RetireCustomAgent
              action={archiveCustomAgent.bind(null, agent.id)}
            />
          </div>
        </Card>
      </div>
    </>
  );
}
