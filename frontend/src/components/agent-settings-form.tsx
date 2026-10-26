"use client";

import { useActionState } from "react";

import { DialogField } from "@/components/action-dialog";
import { ErrorAlert, buttonClass } from "@/components/ui";
import type { Agent } from "@/lib/api-types";
import type { FormState } from "@/lib/form-state";

/**
 * Settings of one AI agent: the switch, the monthly token budget and the tools it may use.
 * Tenant admins only (the page decides; the API checks again). A switch applies from the
 * agent's next question - a conversation already running stops at its next step.
 */
export function AgentSettingsForm({
  agent,
  action,
  initialState,
}: {
  agent: Agent;
  action: (state: FormState, formData: FormData) => Promise<FormState>;
  initialState: FormState;
}) {
  const [state, formAction, pending] = useActionState(action, initialState);
  const v = state.values;
  const e = state.fieldErrors;
  const id = (name: string) => `${agent.key}-${name}`;
  const budget =
    v.budget ??
    (agent.budget_is_default ? "" : String(agent.monthly_token_budget));
  const chosen = v.tools_chosen
    ? v.tools_chosen.split(",")
    : agent.allowed_tools;
  const enabled = v.enabled !== undefined ? v.enabled === "on" : agent.enabled;

  return (
    <form
      key={state.attempt}
      action={formAction}
      noValidate
      className="mt-5 space-y-4 border-t border-slate-100 pt-4"
    >
      {state.error && (
        <ErrorAlert
          title="The settings could not be saved"
          error={state.error}
        />
      )}
      <div>
        <label className="flex items-center gap-2 text-sm font-medium text-slate-800">
          <input
            type="checkbox"
            name="enabled"
            defaultChecked={enabled}
            id={id("enabled")}
          />
          Switched on
        </label>
        <p className="mt-1 text-xs text-slate-500">
          A change applies from the next question. A conversation that is
          running stops at its next step.
        </p>
      </div>
      <DialogField
        id={id("budget")}
        label="Monthly token budget"
        error={e.budget}
        hint="Leave empty to use the standard limit. Whole numbers; commas are fine."
      >
        {(p) => (
          <input
            name="budget"
            inputMode="numeric"
            defaultValue={budget}
            placeholder={
              agent.budget_is_default
                ? agent.monthly_token_budget.toLocaleString("en-US")
                : "Standard limit"
            }
            {...p}
          />
        )}
      </DialogField>
      {agent.all_tools.length > 0 && (
        <fieldset>
          <legend className="text-sm font-medium text-slate-700">
            Tools it may use
          </legend>
          <p className="text-xs text-slate-500">
            You can switch tools off, never add new ones.
          </p>
          <ul className="mt-2 grid gap-1 sm:grid-cols-2">
            {agent.all_tools.map((tool) => (
              <li key={tool}>
                <label className="flex items-center gap-2 font-mono text-xs text-slate-700">
                  <input
                    type="checkbox"
                    name="tools"
                    value={tool}
                    defaultChecked={chosen.includes(tool)}
                  />
                  {tool}
                </label>
              </li>
            ))}
          </ul>
        </fieldset>
      )}
      <button
        type="submit"
        disabled={pending}
        className={buttonClass("primary")}
      >
        {pending ? "Saving…" : "Save settings"}
      </button>
    </form>
  );
}
