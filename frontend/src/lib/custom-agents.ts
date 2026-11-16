/**
 * Custom agent helpers (ADR 0034) that need no server: the API's codes in plain words, where each
 * kind of record lives, how an agent's state is described and how the definition form is read. The
 * API decides everything again - who may define, try or run, and what the menus allow.
 */

import type { ApiErrorInfo } from "@/lib/api-error";
import type {
  CustomAgent,
  CustomAgentMenuItem,
  CustomAgentRecordType,
  CustomAgentRun,
  CustomAgentTrial,
} from "@/lib/api-types";
import { isUuid } from "@/lib/communications";

export const RECORD_TYPE_LABELS: Record<CustomAgentRecordType, string> = {
  lead: "Lead",
  account: "Account",
  deal: "Deal",
};

/** "a lead", "an account", "a deal" - for sentences. */
export const recordNoun = (type: CustomAgentRecordType): string =>
  `${type === "account" ? "an" : "a"} ${type}`;

/** Where a record of each kind is shown. Throws for an id that is not an id (a tampered form). */
export function recordPath(type: CustomAgentRecordType, id: string): string {
  if (!isUuid(id)) throw new Error("invalid record");
  if (type === "lead") return `/leads/${id}`;
  if (type === "account") return `/accounts/${id}`;
  return `/opportunities/${id}`;
}

const ERROR_TEXTS: Record<string, string> = {
  custom_agent_record_not_found: "Record not found.",
  custom_agent_not_found: "This custom agent no longer exists.",
  custom_agent_answer_invalid:
    "The agent did not give a usable answer. Please try again.",
  custom_agent_needs_trial:
    "This version of the agent has not been tried yet. Ask an administrator to run a dry run first.",
  agent_unavailable:
    "This agent is switched off. An administrator can switch it on on its page.",
  agent_budget_reached: "This agent has reached its limit for this month.",
  assistant_unavailable: "The assistant is not available right now.",
  version_conflict:
    "Someone else changed this agent. Reload the page and try again.",
};

/** A code from the API in plain words; the API's own text when it has no special wording (a
 * definition problem or a limit already comes with its own sentence). */
export function customAgentErrorText(
  code: string | undefined | null,
  fallback: string,
): string {
  return (code && ERROR_TEXTS[code]) || fallback;
}

/** What a run came to, for the record page. */
export const OUTCOME_TEXT: Record<string, string> = {
  proposed:
    "The agent made a suggestion. Nothing changes until a different person approves it.",
  no_proposal: "The agent had nothing to suggest.",
  blocked:
    "The agent made a suggestion, but the safety check stopped it, so nothing was proposed.",
};

export function outcomeText(outcome: string): string {
  return OUTCOME_TEXT[outcome] ?? OUTCOME_TEXT.no_proposal;
}

/** What a dry run says the agent would do. */
export const ACTION_TEXT: Record<string, string> = {
  none: "Suggest nothing",
  set_status: "Change the lead's status",
  create_task: "Create a follow-up task",
};

export type AgentStateInfo = { label: string; tone: "good" | "wait" | "off" };

/** The agent's state in words: whether it can be run and what is missing. */
export function agentState(
  agent: Pick<CustomAgent, "enabled" | "tried">,
): AgentStateInfo {
  if (agent.enabled && agent.tried)
    return { label: "Switched on", tone: "good" };
  if (agent.enabled)
    return {
      label: "Switched on - the new version needs a dry run",
      tone: "wait",
    };
  if (agent.tried) return { label: "Ready to switch on", tone: "wait" };
  return { label: "Needs a dry run, then switching on", tone: "off" };
}

/** Whether a run button should be offered: on, and the current version tried. */
export const isRunnable = (
  agent: Pick<CustomAgent, "enabled" | "tried">,
): boolean => agent.enabled && agent.tried;

/** The one kind of record a set of read sets is about, or null for none / a mix. */
export function recordTypeOf(
  chosen: string[],
  menu: CustomAgentMenuItem[],
): CustomAgentRecordType | null {
  const types = new Set(
    chosen.map((key) => menu.find((item) => item.key === key)?.record_type),
  );
  if (types.size !== 1) return null;
  const [only] = [...types];
  return only === "lead" || only === "account" || only === "deal" ? only : null;
}

/** Whether a suggestion kind can be used with the read sets chosen so far (a lead's status needs
 * an agent that reads a lead). The API checks again. */
export function kindAllowed(kind: string, type: CustomAgentRecordType | null) {
  return kind !== "lead.set_status" || type === null || type === "lead";
}

export type DefinitionValues = {
  name: string;
  purpose: string;
  instruction: string;
  read_sets: string[];
  suggestion_kinds: string[];
};

/** The definition form as the API wants it. Nothing is invented here: the menus and the lengths
 * are checked by the API, which answers with plain messages. */
export function definitionFromForm(formData: FormData): DefinitionValues {
  return {
    name: String(formData.get("name") ?? ""),
    purpose: String(formData.get("purpose") ?? ""),
    instruction: String(formData.get("instruction") ?? ""),
    read_sets: formData.getAll("read_sets").map(String),
    suggestion_kinds: formData.getAll("suggestion_kinds").map(String),
  };
}

/** The same values as strings, to keep a form filled in after a refusal. */
export function definitionToValues(
  values: DefinitionValues,
): Record<string, string> {
  return {
    name: values.name,
    purpose: values.purpose,
    instruction: values.instruction,
    read_sets: values.read_sets.join(","),
    suggestion_kinds: values.suggestion_kinds.join(","),
  };
}

export function splitList(value: string | undefined): string[] {
  return value ? value.split(",").filter(Boolean) : [];
}

export const AGENT_KEY = /^custom_[a-z]{12}$/;

/** What a dry run and a run keep between attempts (a "use server" file may export only async
 * functions, so the states live here). */
export type TrialState = {
  attempt: number;
  fieldErrors: Record<string, string>;
  error: ApiErrorInfo | null;
  trial: CustomAgentTrial | null;
  values: Record<string, string>;
};
export const initialTrialState: TrialState = {
  attempt: 0,
  fieldErrors: {},
  error: null,
  trial: null,
  values: {},
};

export type RunState = {
  attempt: number;
  error: ApiErrorInfo | null;
  result: CustomAgentRun | null;
};
export const initialRunState: RunState = {
  attempt: 0,
  error: null,
  result: null,
};
