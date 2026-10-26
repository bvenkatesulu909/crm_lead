import type { Agent } from "@/lib/api-types";

/**
 * AI agent registry helpers (ADR 0016) that need no server: the state in words, number
 * formatting, reading the budget a person typed and the friendlier error texts. The API
 * decides everything again - who may change, what is allowed.
 */

export type AgentState = "on" | "off" | "warning" | "limit";

export const AGENT_STATE_LABELS: Record<AgentState, string> = {
  on: "On",
  off: "Switched off",
  warning: "Near its limit",
  limit: "Limit reached",
};

/** The state as one word: switched off beats everything, then how much of the month is used. */
export function agentState(
  agent: Pick<Agent, "enabled" | "percent_used">,
): AgentState {
  if (!agent.enabled) return "off";
  if (agent.percent_used >= 100) return "limit";
  if (agent.percent_used >= 80) return "warning";
  return "on";
}

export function formatTokens(count: number): string {
  return `${count.toLocaleString("en-US")} ${count === 1 ? "token" : "tokens"}`;
}

const MAX_BUDGET = 10_000_000_000;

/** An empty box means "use the standard limit" (null); otherwise whole numbers only. */
export function parseBudget(
  text: string,
): { value: number | null } | { error: string } {
  const cleaned = text.trim().replace(/[,\s_]/g, "");
  if (cleaned === "") return { value: null };
  if (!/^\d+$/.test(cleaned))
    return {
      error: "Use whole numbers only, for example 2000000 or 2,000,000.",
    };
  const value = Number(cleaned);
  if (value < 1 || value > MAX_BUDGET)
    return {
      error: `The budget must be between 1 and ${MAX_BUDGET.toLocaleString("en-US")} tokens.`,
    };
  return { value };
}

/** What to send as `allowed_tools`: null (all tools, the default) or the sorted list. */
export function toggledTools(chosen: string[], all: string[]): string[] | null {
  const picked = all.filter((tool) => chosen.includes(tool));
  return picked.length === all.length ? null : [...picked].sort();
}

const ERRORS: Record<string, string> = {
  version_conflict:
    "Someone else changed this agent in the meantime. Reload the page and try again.",
  agent_not_found: "This agent doesn't exist.",
};

export function agentErrorText(code: string | undefined, message: string) {
  return (code && ERRORS[code]) || message;
}
