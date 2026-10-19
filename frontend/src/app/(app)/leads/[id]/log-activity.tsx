"use client";

import { useActionState, useState } from "react";

import { DialogField } from "@/components/action-dialog";
import { ErrorAlert, buttonClass } from "@/components/ui";
import type { FormState } from "@/lib/form-state";
import { initialFormState } from "@/lib/form-state";

const KINDS = [
  ["call", "Call"],
  ["meeting", "Meeting"],
  ["email", "E-mail"],
  ["note", "Note"],
] as const;

/**
 * Log a call, meeting, e-mail or note on a lead (POST /leads/{id}/activities).
 * "When" is entered in the user's local time; the browser converts it to an exact moment
 * (ISO with time zone) so the server never has to guess the time zone.
 */
export function LogActivityForm({
  action,
}: {
  action: (state: FormState, formData: FormData) => Promise<FormState>;
}) {
  const [state, formAction, pending] = useActionState(action, initialFormState);
  const [when, setWhen] = useState(state.values.when_local ?? "");
  const moment = when ? new Date(when) : null;
  const iso =
    moment && !Number.isNaN(moment.getTime()) ? moment.toISOString() : "";
  const e = state.fieldErrors;

  return (
    <form key={state.attempt} action={formAction} noValidate className="space-y-4 border-b border-slate-200 px-5 py-4">
      {state.error && <ErrorAlert title="The activity could not be saved" error={state.error} />}
      <div className="grid gap-4 sm:grid-cols-[10rem_1fr]">
        <DialogField id="activity-kind" label="Type" error={e.kind}>
          {(p) => (
            <select name="kind" defaultValue={state.values.kind ?? "call"} {...p}>
              {KINDS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          )}
        </DialogField>
        <DialogField id="activity-subject" label="Subject" error={e.subject} hint="For example: Discussed pricing for 50 licences.">
          {(p) => <input name="subject" maxLength={200} defaultValue={state.values.subject} {...p} />}
        </DialogField>
      </div>
      <DialogField id="activity-body" label="Notes" optional error={e.body}>
        {(p) => <textarea name="body" rows={3} maxLength={5000} defaultValue={state.values.body} {...p} />}
      </DialogField>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <DialogField id="activity-when" label="When" optional error={e.occurred_at} hint="Leave empty for now.">
          {(p) => (
            <input type="datetime-local" name="when_local" value={when} onChange={(ev) => setWhen(ev.target.value)} {...p} />
          )}
        </DialogField>
        <input type="hidden" name="occurred_at" value={iso} />
        <button type="submit" disabled={pending} className={buttonClass("primary")}>
          {pending ? "Saving…" : "Log activity"}
        </button>
      </div>
    </form>
  ); // prettier-ignore
}
