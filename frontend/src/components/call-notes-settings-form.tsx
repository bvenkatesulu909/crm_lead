"use client";

import { useActionState } from "react";

import { ErrorAlert, buttonClass } from "@/components/ui";
import type { CallNotesSettings } from "@/lib/call-notes";
import type { FormState } from "@/lib/form-state";

/**
 * Choose the checklist frame of call notes. Each frame lists its fields so an administrator can see
 * what will be asked. A refused save keeps the choice that was made (React empties uncontrolled
 * fields after an action).
 */
export function CallNotesSettingsForm({
  settings,
  action,
  initialState,
}: {
  settings: CallNotesSettings;
  action: (state: FormState, formData: FormData) => Promise<FormState>;
  initialState: FormState;
}) {
  const [state, formAction, pending] = useActionState(action, initialState);
  const chosen = state.values.framework ?? settings.framework;

  return (
    <form
      key={state.attempt}
      action={formAction}
      noValidate
      className="space-y-4"
    >
      {state.error && (
        <ErrorAlert
          title="The setting could not be saved"
          error={state.error}
        />
      )}
      <fieldset>
        <legend className="text-sm font-medium text-slate-900">
          Checklist frame
        </legend>
        <div className="mt-2 space-y-3">
          {settings.frameworks.map((frame) => (
            <label
              key={frame.key}
              className="flex items-start gap-2 rounded-md border border-slate-200 p-3 text-sm text-slate-800"
            >
              <input
                type="radio"
                name="framework"
                value={frame.key}
                defaultChecked={chosen === frame.key}
                className="mt-0.5"
              />
              <span>
                <span className="font-medium">{frame.title}</span>
                <span className="mt-1 block text-xs text-slate-600">
                  {frame.fields.map((f) => f.label).join(", ")}
                </span>
              </span>
            </label>
          ))}
        </div>
        {state.fieldErrors.framework && (
          <p role="alert" className="mt-1 text-sm text-red-700">
            {state.fieldErrors.framework}
          </p>
        )}
      </fieldset>
      <button
        type="submit"
        className={buttonClass("primary")}
        disabled={pending}
      >
        Save
      </button>
    </form>
  );
}
