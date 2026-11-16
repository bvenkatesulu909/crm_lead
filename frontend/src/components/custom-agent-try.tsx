"use client";

import { useActionState, useId } from "react";

import { DialogField } from "@/components/action-dialog";
import { ErrorAlert, buttonClass } from "@/components/ui";
import { ACTION_TEXT, type TrialState } from "@/lib/custom-agents";

export type RecordChoice = { id: string; label: string };

/**
 * The dry run (ADR 0034): pick one real record and see what the agent WOULD suggest. Nothing is
 * proposed or changed; the model call counts against the agent's token budget. A usable answer
 * counts as the trial of the current version, which is needed before the agent can be switched
 * on. The text a model wrote is shown as plain text.
 */
export function CustomAgentTry({
  recordLabel,
  choices,
  initialState,
  action,
}: {
  recordLabel: string;
  choices: RecordChoice[];
  initialState: TrialState;
  action: (state: TrialState, formData: FormData) => Promise<TrialState>;
}) {
  const id = useId();
  const [state, formAction, pending] = useActionState(action, initialState);
  const trial = state.trial;
  return (
    <form
      action={formAction}
      noValidate
      aria-label="Try the agent"
      className="space-y-4"
    >
      {state.error && (
        <ErrorAlert title="The dry run did not work" error={state.error} />
      )}
      <DialogField
        id={`${id}-record`}
        label={recordLabel}
        error={state.fieldErrors.record_id}
      >
        {(p) => (
          <select
            name="record_id"
            defaultValue={state.values.record_id ?? ""}
            {...p}
          >
            <option value="">Choose…</option>
            {choices.map((choice) => (
              <option key={choice.id} value={choice.id}>
                {choice.label}
              </option>
            ))}
          </select>
        )}
      </DialogField>
      <button
        type="submit"
        disabled={pending}
        className={buttonClass("secondary")}
      >
        {pending ? "Trying…" : "Try it (dry run)"}
      </button>
      {trial && (
        <div
          role="status"
          className="space-y-1 rounded-md border border-slate-200 bg-slate-50 p-3 text-sm"
        >
          <p className="font-medium text-slate-900">
            Version {trial.version_no} would:{" "}
            {ACTION_TEXT[trial.action] ?? trial.action}
          </p>
          {trial.would_propose && (
            <p className="whitespace-pre-line break-words text-slate-800">
              {trial.would_propose}
            </p>
          )}
          <p className="whitespace-pre-line break-words text-slate-700">
            Reason: {trial.reason}
          </p>
          <p className="text-xs text-slate-500">
            It was shown: {trial.sets_shown.join(", ") || "nothing"}. Nothing
            was proposed or changed, and this version now counts as tried.
          </p>
        </div>
      )}
    </form>
  );
}
