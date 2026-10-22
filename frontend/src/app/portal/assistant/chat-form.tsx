"use client";

import { useActionState, useRef, useState } from "react";

import { ErrorAlert, buttonClass } from "@/components/ui";
import { VoiceRecorder } from "@/components/voice-recorder";
import type { FormState } from "@/lib/form-state";

type Action = (state: FormState, formData: FormData) => Promise<FormState>;

/** Customer message box with server-first voice recording (browser speech fallback). */
export function ChatForm({
  action,
  initialState,
}: {
  action: Action;
  initialState: FormState;
}) {
  const [text, setText] = useState(initialState.values.text ?? "");
  const [state, formAction, pending] = useActionState(
    async (previous: FormState, formData: FormData) => {
      const next = await action(previous, formData);
      setText(next.values.text ?? "");
      return next;
    },
    initialState,
  );
  const formRef = useRef<HTMLFormElement>(null);
  const error = state.fieldErrors.text;

  return (
    <form ref={formRef} key={state.attempt} action={formAction} noValidate className="space-y-3 border-t border-slate-200 p-4">
      {state.error && <ErrorAlert title="Your message could not be answered" error={state.error} />}
      <label htmlFor="assistant-text" className="sr-only">Your question</label>
      <textarea
        id="assistant-text"
        name="text"
        rows={3}
        maxLength={2000}
        value={text}
        onChange={(event) => setText(event.target.value)}
        placeholder="Ask about your orders, invoices or support tickets…"
        aria-invalid={Boolean(error)}
        aria-describedby={error ? "assistant-text-error" : undefined}
        className="block w-full rounded-md border-0 px-3 py-2 text-sm ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-brand-600"
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            e.currentTarget.form?.requestSubmit();
          }
        }}
      />
      {error && <p id="assistant-text-error" className="text-sm text-red-700">{error}</p>}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-slate-500">Enter to send · Shift+Enter for a new line</p>
        <div className="flex flex-wrap items-center gap-2">
          <VoiceRecorder
            label="Speak"
            onComplete={() => window.setTimeout(() => formRef.current?.requestSubmit(), 50)}
            onTranscript={(transcript) =>
              setText((current) => (current ? current + " " + transcript : transcript))
            }
          />
          <button type="submit" disabled={pending} className={buttonClass("primary")}>
            {pending ? "Thinking…" : "Send"}
          </button>
        </div>
      </div>
    </form>
  ); // prettier-ignore
}