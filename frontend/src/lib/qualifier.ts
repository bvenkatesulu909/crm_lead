import { isUuid } from "@/lib/communications";

/**
 * Qualifier helpers (docs/qualifier.md) that need no server: plain words for the decisions and
 * the errors, reading the steps a person typed, and the check of the form before it is sent.
 * The API decides everything again - who may ask, what a valid procedure is, the limits.
 */

export const DECISION_LABELS: Record<string, string> = {
  qualify: "Qualify the lead",
  unqualify: "Mark the lead unqualified",
  contact_first: "Call the lead first",
  need_info: "Ask the buyer for more details",
  no_change: "No change suggested",
};

export const OUTCOME_TEXTS: Record<string, string> = {
  proposed: "A proposal is waiting for approval.",
  no_proposal: "Nothing needed to be proposed.",
  blocked: "The safety check refused the proposal, so nothing was created.",
};

export function decisionLabel(decision: string): string {
  return DECISION_LABELS[decision] ?? decision.replaceAll("_", " ");
}

export function outcomeText(outcome: string): string {
  return OUTCOME_TEXTS[outcome] ?? outcome;
}

/** "steps 1, 2 and 3 matched" - the numbers are the procedure's own numbering. */
export function matchedText(steps: number[]): string {
  if (steps.length === 0) return "No step matched";
  const list =
    steps.length === 1
      ? String(steps[0])
      : `${steps.slice(0, -1).join(", ")} and ${steps[steps.length - 1]}`;
  return steps.length === 1 ? `Step ${list} matched` : `Steps ${list} matched`;
}

const ERROR_TEXTS: Record<string, string> = {
  no_active_qualification_procedure:
    "No qualification procedure has been written yet. Ask an administrator to write one.",
  lead_not_found: "Lead not found.",
  assessment_invalid:
    "The assistant did not give a usable answer. Please try again.",
  agent_unavailable: "The Qualifier is switched off for your organisation.",
  agent_budget_reached: "The Qualifier has reached its limit for this month.",
  assistant_unavailable: "The assistant is not available right now.",
  qualification_procedure_changed:
    "Someone else changed the procedure. Reload the page and try again.",
};

/** A code from the API in plain words; the API's own text when it has no special wording. */
export function qualifierErrorText(
  code: string | undefined | null,
  fallback: string,
): string {
  return (code && ERROR_TEXTS[code]) || fallback;
}

export const MAX_STEPS = 20;
export const MIN_STEP_CHARS = 3;
export const MAX_STEP_CHARS = 300;
export const MAX_TOTAL_CHARS = 4000;
export const MAX_NAME_CHARS = 100;

/** One step per line; a leading "1." or "2)" is dropped (the numbers are added again on show). */
export function parseSteps(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) =>
      line
        .trim()
        .replace(/^\d+\s*[.)]\s*/, "")
        .trim(),
    )
    .filter((line) => line.length > 0);
}

export function stepsToText(steps: string[]): string {
  return steps.join("\n");
}

export type ProcedureInput = { name: string; steps: string[] };

/** Checks the form the way the API will; the API still decides. */
export function checkProcedureForm(
  name: string,
  stepsText: string,
):
  | { ok: true; data: ProcedureInput }
  | { ok: false; fieldErrors: Record<string, string> } {
  const fieldErrors: Record<string, string> = {};
  const cleanName = name.trim();
  if (cleanName.length < 1 || cleanName.length > MAX_NAME_CHARS)
    fieldErrors.name = `Enter a name of up to ${MAX_NAME_CHARS} characters.`;
  const steps = parseSteps(stepsText);
  if (steps.length === 0) fieldErrors.steps = "Write at least one step.";
  else if (steps.length > MAX_STEPS)
    fieldErrors.steps = `At most ${MAX_STEPS} steps.`;
  else {
    const short = steps.findIndex((s) => s.length < MIN_STEP_CHARS);
    const long = steps.findIndex((s) => s.length > MAX_STEP_CHARS);
    if (short >= 0)
      fieldErrors.steps = `Step ${short + 1} is too short (at least ${MIN_STEP_CHARS} characters).`;
    else if (long >= 0)
      fieldErrors.steps = `Step ${long + 1} is too long (at most ${MAX_STEP_CHARS} characters).`;
    else if (steps.join("").length > MAX_TOTAL_CHARS)
      fieldErrors.steps = `Together the steps may have at most ${MAX_TOTAL_CHARS} characters.`;
  }
  if (Object.keys(fieldErrors).length > 0) return { ok: false, fieldErrors };
  return { ok: true, data: { name: cleanName, steps } };
}

/** Where the lead page is; throws for a tampered id (the id comes from the browser). */
export function leadPath(leadId: string): string {
  if (!isUuid(leadId)) throw new Error("invalid lead");
  return `/leads/${leadId}`;
}
