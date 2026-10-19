"use client";

import Link from "next/link";
import { useActionState, useState } from "react";

import { DialogField } from "@/components/action-dialog";
import { CATEGORY_LABELS, PRIORITY_LABELS } from "@/components/tickets";
import { ErrorAlert, buttonClass } from "@/components/ui";
import { TICKET_CATEGORIES, TICKET_PRIORITIES } from "@/lib/api-types";
import type { FormState } from "@/lib/form-state";

type Action = (state: FormState, formData: FormData) => Promise<FormState>;

/** Open a ticket: used by customers (portal) and by staff (with priority). */
export function TicketForm({
  action,
  initialState,
  accounts,
  defaultAccountId,
  withPriority = false,
  cancelHref,
  submitLabel = "Submit ticket",
}: {
  action: Action;
  initialState: FormState;
  accounts: { id: string; name: string }[];
  defaultAccountId?: string;
  withPriority?: boolean;
  cancelHref: string;
  submitLabel?: string;
}) {
  const [state, formAction, pending] = useActionState(action, initialState);
  const errors = state.fieldErrors;
  const values = state.values;
  const count = Object.keys(errors).length;

  return (
    <form key={state.attempt} action={formAction} noValidate className="space-y-5">
      {state.error && <ErrorAlert title="The ticket could not be submitted" error={state.error} />}
      {count > 0 && (
        <div role="alert" className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          Please correct {count === 1 ? "1 field" : `${count} fields`} below.
        </div>
      )}
      <DialogField id="ticket-account" label="Account" error={errors.account_id}>
        {(props) => (
          <select name="account_id" defaultValue={values.account_id ?? defaultAccountId ?? (accounts.length === 1 ? accounts[0].id : "")} {...props}>
            <option value="" disabled>Choose an account…</option>
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        )}
      </DialogField>
      {withPriority && (
        <DialogField id="ticket-priority" label="Priority" error={errors.priority} hint="Sets the response and resolution deadlines.">
          {(props) => (
            <select name="priority" defaultValue={values.priority ?? "normal"} {...props}>
              {TICKET_PRIORITIES.map((p) => <option key={p} value={p}>{PRIORITY_LABELS[p]}</option>)}
            </select>
          )}
        </DialogField>
      )}
      <DialogField id="ticket-category" label="What is it about?" error={errors.category}>
        {(props) => (
          <select name="category" defaultValue={values.category ?? "question"} {...props}>
            {TICKET_CATEGORIES.map((c) => <option key={c} value={c}>{CATEGORY_LABELS[c]}</option>)}
          </select>
        )}
      </DialogField>
      <DialogField id="ticket-subject" label="Subject" error={errors.subject}>
        {(props) => <input name="subject" maxLength={200} defaultValue={values.subject} {...props} />}
      </DialogField>
      <DialogField id="ticket-description" label="Description" error={errors.description}
        hint="What happened, what you expected, and any reference numbers.">
        {(props) => <textarea name="description" rows={6} maxLength={10000} defaultValue={values.description} {...props} />}
      </DialogField>
      <div className="flex justify-end gap-3 border-t border-slate-200 pt-5">
        <Link href={cancelHref} className={buttonClass("secondary")}>Cancel</Link>
        <button type="submit" disabled={pending} className={buttonClass("primary")}>
          {pending ? "Submitting…" : submitLabel}
        </button>
      </div>
    </form>
  ); // prettier-ignore
}

/**
 * Reply to a ticket. Staff choose between a reply the CUSTOMER sees and an internal note;
 * the button text always says which one is about to be sent.
 */
export function ReplyForm({
  action,
  initialState,
  staff = false,
}: {
  action: Action;
  initialState: FormState;
  staff?: boolean;
}) {
  const [state, formAction, pending] = useActionState(action, initialState);
  const [visibility, setVisibility] = useState<"public" | "internal">(
    (state.values.visibility as "public" | "internal") ?? "public",
  );
  const internal = staff && visibility === "internal";

  return (
    <form key={state.attempt} action={formAction} noValidate className="space-y-4 border-t border-slate-200 px-5 py-4">
      {state.error && <ErrorAlert title="Your message could not be sent" error={state.error} />}
      {staff && (
        <fieldset>
          <legend className="text-sm font-medium text-slate-700">Type of message</legend>
          <div className="mt-2 flex flex-wrap gap-4 text-sm">
            <label className="flex items-center gap-2">
              <input type="radio" name="visibility" value="public" checked={!internal} onChange={() => setVisibility("public")} />
              Reply to customer
            </label>
            <label className="flex items-center gap-2">
              <input type="radio" name="visibility" value="internal" checked={internal} onChange={() => setVisibility("internal")} />
              Internal note (staff only)
            </label>
          </div>
        </fieldset>
      )}
      <DialogField id="reply-body" label={internal ? "Internal note" : staff ? "Message to customer" : "Your reply"} error={state.fieldErrors.body}>
        {(props) => <textarea name="body" rows={4} maxLength={10000} defaultValue={state.values.body} {...props} />}
      </DialogField>
      <div className="flex justify-end">
        <button type="submit" disabled={pending} className={buttonClass(internal ? "secondary" : "primary")}>
          {pending ? "Sending…" : internal ? "Add internal note" : staff ? "Send reply to customer" : "Send reply"}
        </button>
      </div>
    </form>
  ); // prettier-ignore
}
