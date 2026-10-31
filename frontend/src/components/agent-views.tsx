import type { ReactNode } from "react";

import { Card, cx } from "@/components/ui";
import type { Agent } from "@/lib/api-types";
import {
  AGENT_STATE_LABELS,
  type AgentState,
  agentState,
  formatTokens,
} from "@/lib/agents";

const BADGE: Record<AgentState, string> = {
  on: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  off: "bg-slate-100 text-slate-700 ring-slate-300",
  warning: "bg-amber-50 text-amber-800 ring-amber-200",
  limit: "bg-red-50 text-red-700 ring-red-200",
};
const BAR: Record<AgentState, string> = {
  on: "bg-emerald-500",
  off: "bg-slate-400",
  warning: "bg-amber-500",
  limit: "bg-red-500",
};

/** The state as a word (never colour alone). */
export function AgentStateBadge({ agent }: { agent: Agent }) {
  const state = agentState(agent);
  return (
    <span
      className={cx(
        "inline-flex rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ring-inset",
        BADGE[state],
      )}
    >
      {AGENT_STATE_LABELS[state]}
    </span>
  );
}

/**
 * One AI agent: what it is, its state, this month's usage and how many tools it may use.
 * `children` is the slot for the settings form (shown only to people who may change it).
 * All texts come from the server and are shown as plain text.
 */
export function AgentCard({
  agent,
  children,
}: {
  agent: Agent;
  children?: ReactNode;
}) {
  const state = agentState(agent);
  const headingId = `agent-${agent.key}`;
  const shown = Math.min(100, Math.max(0, agent.percent_used));
  return (
    <article aria-labelledby={headingId}>
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2
              id={headingId}
              className="text-base font-semibold text-slate-900"
            >
              {agent.title}
            </h2>
            <p className="mt-1 text-sm text-slate-600">{agent.description}</p>
          </div>
          <AgentStateBadge agent={agent} />
        </div>
        {!agent.uses_model ? (
          <p className="mt-4 text-sm text-slate-700">
            {agent.calls === 0
              ? "No checks this month"
              : `${agent.calls} ${agent.calls === 1 ? "check" : "checks"} this month`}
            <span className="text-xs text-slate-500">
              {" "}
              - uses no language model, so there is no token budget
            </span>
          </p>
        ) : (
          <div className="mt-4">
            <div
              role="progressbar"
              aria-label={`${agent.title}: tokens used this month`}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={shown}
              className="h-2 overflow-hidden rounded-full bg-slate-100"
            >
              <div
                className={cx("h-full rounded-full", BAR[state])}
                style={{ width: `${shown}%` }}
              />
            </div>
            <p className="mt-2 text-sm text-slate-700">
              {agent.used_tokens.toLocaleString("en-US")} of{" "}
              {formatTokens(agent.monthly_token_budget)} used this month
              {agent.budget_is_default && (
                <span className="text-slate-500"> (the standard limit)</span>
              )}
            </p>
            <p className="text-xs text-slate-500">
              {agent.calls} {agent.calls === 1 ? "call" : "calls"} -{" "}
              {agent.all_tools.length === 0
                ? "uses no tools"
                : `${agent.allowed_tools.length} of ${agent.all_tools.length} tools allowed`}
            </p>
          </div>
        )}
        {children}
      </Card>
    </article>
  );
}
