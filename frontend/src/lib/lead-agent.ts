/**
 * Lead agent helpers (ADR 0022) that need no server: the API's codes in plain words and where to
 * go back to after asking. The API decides everything again - who may ask, the limits.
 */

const ERROR_TEXTS: Record<string, string> = {
  lead_not_found: "Lead not found.",
  lead_agent_invalid_answer:
    "The assistant did not give a usable answer. Please try again.",
  agent_unavailable:
    "The lead agent is switched off. An administrator can switch it on under AI agents.",
  agent_budget_reached: "The lead agent has reached its limit for this month.",
  assistant_unavailable: "The assistant is not available right now.",
};

/** A code from the API in plain words; the API's own text when it has no special wording (a
 * limit, for example, already comes with its own sentence). */
export function leadAgentErrorText(
  code: string | undefined | null,
  fallback: string,
): string {
  return (code && ERROR_TEXTS[code]) || fallback;
}

/** What the lead page says after a run: only the outcome codes the API can return. */
export const OUTCOME_DONE: Record<string, string> = {
  proposed: "lead-agent-proposed",
  no_suggestion: "lead-agent-nothing",
  blocked: "lead-agent-blocked",
};

export function outcomeDone(outcome: string): string {
  return OUTCOME_DONE[outcome] ?? "lead-agent-nothing";
}
