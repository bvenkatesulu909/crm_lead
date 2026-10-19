"use client";

import { useActionState, useState } from "react";

import { DialogField } from "@/components/action-dialog";
import { ErrorAlert, buttonClass, cx } from "@/components/ui";
import { PRIORITIES, type ActivityKind } from "@/lib/api-types";
import type { FormState } from "@/lib/form-state";
import { initialFormState } from "@/lib/form-state";
import { KIND_LABELS, PRIORITY_LABELS, localToIso } from "@/lib/pipeline";

const REMINDERS = [
  ["", "No reminder"],
  ["0", "At the due time"],
  ["15", "15 minutes before"],
  ["60", "1 hour before"],
  ["1440", "1 day before"],
] as const;

/**
 * One form for both kinds of work:
 *   "Plan" - a task or follow-up call/meeting/e-mail with a due date and optional reminder;
 *   "Log"  - something that already happened (call, meeting, e-mail, note) with its outcome.
 * Dates are typed in the user's local time and sent as exact moments (ISO with time zone).
 */
export function ActivityComposer({
  action,
  assignees,
  defaultMode = "plan",
  planOnly = false,
}: {
  action: (state: FormState, formData: FormData) => Promise<FormState>;
  /** Colleagues the user may give work to; omitted = only themself. */
  assignees?: { id: string; name: string }[];
  defaultMode?: "plan" | "log";
  /** Only planning (e.g. on leads, which keep their own log of calls and notes). */
  planOnly?: boolean;
}) {
  const [state, formAction, pending] = useActionState(action, initialFormState);
  const [mode, setMode] = useState<"plan" | "log">(
    state.values.status === "done"
      ? "log"
      : state.values.status === "open"
        ? "plan"
        : defaultMode,
  );
  const [kind, setKind] = useState<ActivityKind>(
    (state.values.kind as ActivityKind) ?? (mode === "plan" ? "task" : "call"),
  );
  const [due, setDue] = useState(state.values.due_local ?? "");
  const [offset, setOffset] = useState(state.values.reminder_offset ?? "");
  const [occurred, setOccurred] = useState(state.values.occurred_local ?? "");
  const e = state.fieldErrors;
  const plan = mode === "plan";
  const dueIso = localToIso(due);
  const reminderIso =
    dueIso && offset !== ""
      ? new Date(Date.parse(dueIso) - Number(offset) * 60_000).toISOString()
      : "";
  const kinds: ActivityKind[] = plan
    ? ["task", "call", "meeting", "email"]
    : ["call", "meeting", "email", "note"];

  return (
    <form key={state.attempt} action={formAction} noValidate className="space-y-4">
      {state.error && <ErrorAlert title="This could not be saved" error={state.error} />}
      {/* Every field error, also for fields the current mode doesn't show - never silent. */}
      {Object.keys(e).length > 0 && (
        <p role="alert" className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          Please check: {Object.values(e).join(" ")}
        </p>
      )}
      <fieldset>
        <legend className="sr-only">What do you want to do?</legend>
        <div className="inline-flex rounded-lg bg-slate-100 p-1 text-sm">
          {(planOnly ? (["plan"] as const) : (["plan", "log"] as const)).map((m) => (
            <label key={m} className={cx("cursor-pointer rounded-md px-3 py-1.5 font-medium", mode === m ? "bg-white text-slate-900 shadow-sm" : "text-slate-600")}>
              <input type="radio" name="mode" value={m} checked={mode === m} className="sr-only"
                onChange={() => { setMode(m); setKind(m === "plan" ? "task" : "call"); }} />
              {m === "plan" ? "Plan a task or follow-up" : "Log what happened"}
            </label>
          ))}
        </div>
      </fieldset>
      <input type="hidden" name="status" value={plan ? "open" : "done"} />
      <div className="grid gap-4 sm:grid-cols-[9rem_1fr]">
        <DialogField id="act-kind" label="Type" error={e.kind}>
          {(p) => (
            <select name="kind" value={kind} onChange={(ev) => setKind(ev.target.value as ActivityKind)} {...p}>
              {kinds.map((k) => <option key={k} value={k}>{KIND_LABELS[k]}</option>)}
            </select>
          )}
        </DialogField>
        <DialogField id="act-subject" label="Subject" error={e.subject}>
          {(p) => <input name="subject" maxLength={200} defaultValue={state.values.subject}
            placeholder={plan ? "e.g. Call back about pricing" : "e.g. Discussed renewal"} {...p} />}
        </DialogField>
      </div>
      <DialogField id="act-body" label="Notes" optional error={e.body}>
        {(p) => <textarea name="body" rows={2} maxLength={10000} defaultValue={state.values.body} {...p} />}
      </DialogField>
      {plan ? (
        <div className="grid gap-4 sm:grid-cols-3">
          <DialogField id="act-due" label="Due" optional error={e.due_at}>
            {(p) => <input type="datetime-local" name="due_local" value={due} onChange={(ev) => setDue(ev.target.value)} {...p} />}
          </DialogField>
          <DialogField id="act-reminder" label="Reminder" optional error={e.reminder_at} hint={due ? undefined : "Set a due time first."}>
            {(p) => (
              <select name="reminder_offset" value={offset} onChange={(ev) => setOffset(ev.target.value)} disabled={!due} {...p}>
                {REMINDERS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            )}
          </DialogField>
          <DialogField id="act-priority" label="Priority" error={e.priority}>
            {(p) => (
              <select name="priority" defaultValue={state.values.priority ?? "normal"} {...p}>
                {PRIORITIES.map((x) => <option key={x} value={x}>{PRIORITY_LABELS[x]}</option>)}
              </select>
            )}
          </DialogField>
          <input type="hidden" name="due_at" value={dueIso} />
          <input type="hidden" name="reminder_at" value={reminderIso} />
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          <DialogField id="act-when" label="When" optional error={e.occurred_at} hint="Leave empty for now.">
            {(p) => <input type="datetime-local" name="occurred_local" value={occurred} onChange={(ev) => setOccurred(ev.target.value)} {...p} />}
          </DialogField>
          <DialogField id="act-outcome" label="Outcome" optional error={e.outcome}>
            {(p) => <input name="outcome" maxLength={500} defaultValue={state.values.outcome} placeholder="e.g. Interested, wants a quote" {...p} />}
          </DialogField>
          <input type="hidden" name="occurred_at" value={localToIso(occurred)} />
        </div>
      )}
      <div className="flex flex-wrap items-end justify-between gap-4">
        {assignees && assignees.length > 0 ? (
          <DialogField id="act-assignee" label={plan ? "Assigned to" : "Done by"} error={e.assignee_id}>
            {(p) => (
              <select name="assignee_id" defaultValue={state.values.assignee_id ?? ""} {...p}>
                <option value="">Me</option>
                {assignees.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            )}
          </DialogField>
        ) : <span />}
        <button type="submit" disabled={pending} className={buttonClass("primary")}>
          {pending ? "Saving…" : plan ? "Add to tasks" : "Log activity"}
        </button>
      </div>
    </form>
  ); // prettier-ignore
}
