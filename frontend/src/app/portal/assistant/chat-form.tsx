"use client";

import { useActionState } from "react";

import { ErrorAlert, buttonClass } from "@/components/ui";
import type { FormState } from "@/lib/form-state";

type Action = (state: FormState, formData: FormData) => Promise<FormState>;

/** The message box. While the assistant thinks, the button says so and can't be clicked twice. */
export function ChatForm({
  action,
  initialState,
}: {
  action: Action;
  initialState: FormState;
}) {
  const [state, formAction, pending] = useActionState(action, initialState);
  const error = state.fieldErrors.text;
  return (
    <form key={state.attempt} action={formAction} noValidate className="space-y-3 border-t border-slate-200 p-4">
      {state.error && <ErrorAlert title="Your message could not be answered" error={state.error} />}
      <label htmlFor="assistant-text" className="sr-only">Your question</label>
      <textarea
        id="assistant-text"
        name="text"
        rows={3}
        maxLength={2000}
        defaultValue={state.values.text}
        placeholder="Ask about your orders, invoices or support tickets…"
        aria-invalid={Boolean(error)}
        aria-describedby={error ? "assistant-text-error" : undefined}
        className="block w-full rounded-md border-0 px-3 py-2 text-sm ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-brand-600"
        onKeyDown={(e) => {
          // Enter sends, Shift+Enter makes a new line.
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            e.currentTarget.form?.requestSubmit();
          }
        }}
      />
      {error && <p id="assistant-text-error" className="text-sm text-red-700">{error}</p>}
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-slate-500">Enter to send · Shift+Enter for a new line</p>
        <button type="submit" disabled={pending} className={buttonClass("primary")}>
          {pending ? "Thinking…" : "Send"}
        </button>
      </div>
    </form>
  ); // prettier-ignore
}
