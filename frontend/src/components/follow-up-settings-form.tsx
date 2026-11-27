"use client";

import { useActionState } from "react";

import { DialogField } from "@/components/action-dialog";
import { ErrorAlert, buttonClass } from "@/components/ui";
import type { EmailTemplate } from "@/lib/api-types";
import { NUMBER_FIELDS, type FollowUpSettings } from "@/lib/follow-ups";
import type { FormState } from "@/lib/form-state";

/**
 * The follow-up settings: the switch, the e-mail template the rule fills in, and the limits.
 * A refused save keeps what was typed (React empties uncontrolled fields after an action).
 */
export function FollowUpSettingsForm({
  settings,
  templates,
  action,
  initialState,
}: {
  settings: FollowUpSettings;
  templates: Pick<EmailTemplate, "id" | "name">[];
  action: (state: FormState, formData: FormData) => Promise<FormState>;
  initialState: FormState;
}) {
  const [state, formAction, pending] = useActionState(action, initialState);
  const v = state.values;
  const e = state.fieldErrors;
  const touched = state.attempt > 0;
  const enabled = touched ? v.enabled === "on" : settings.enabled;
  const template = touched
    ? (v.template_id ?? "")
    : (settings.template_id ?? "");

  return (
    <form
      key={state.attempt}
      action={formAction}
      noValidate
      className="space-y-4"
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
            id="follow-up-enabled"
          />
          Make follow-up drafts
        </label>
        <p className="mt-1 text-xs text-slate-500">
          Off until you switch it on. Drafts only wait in the approval queue;
          nothing is sent until a person approves it.
        </p>
      </div>
      <DialogField
        id="follow-up-template"
        label="E-mail template"
        error={e.template_id}
        hint="The draft is this template filled in with the lead's name, so keep it short and personal. Manage templates under E-mail."
      >
        {(p) => (
          <select name="template_id" defaultValue={template} {...p}>
            <option value="">Choose a template</option>
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        )}
      </DialogField>
      {NUMBER_FIELDS.map((field) => (
        <DialogField
          key={field.name}
          id={`follow-up-${field.name}`}
          label={field.label}
          error={e[field.name]}
          hint={field.hint}
        >
          {(p) => (
            <input
              name={field.name}
              inputMode="numeric"
              defaultValue={
                touched ? (v[field.name] ?? "") : String(settings[field.name])
              }
              {...p}
            />
          )}
        </DialogField>
      ))}
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
