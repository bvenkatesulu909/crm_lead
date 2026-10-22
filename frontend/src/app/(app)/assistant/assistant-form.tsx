"use client";

import Link from "next/link";
import { useActionState, useRef } from "react";

import { Card, ErrorAlert, buttonClass } from "@/components/ui";
import { SpeakButton } from "@/components/speak-button";
import { VoiceRecorder } from "@/components/voice-recorder";

import { askStaffAssistant } from "./actions";
import { initialStaffAssistantState } from "./state";

export function StaffAssistantForm() {
  const [state, action, pending] = useActionState(askStaffAssistant, initialStaffAssistantState);
  const questionRef = useRef<HTMLTextAreaElement>(null);
  const formRef = useRef<HTMLFormElement>(null);
  return (
    <div className="space-y-6">
      <Card className="p-5">
        <form ref={formRef} action={action} className="space-y-4">
          {state.error && <ErrorAlert title="The assistant could not answer" error={state.error} />}
           <div>
            <label htmlFor="question" className="block text-sm font-medium text-slate-700">
              Question
            </label>
            <textarea
              ref={questionRef}
              id="question"
              name="question"
              rows={4}
              maxLength={2000}
              defaultValue={state.values.question}
              placeholder="e.g. Show active customers or summarize open support tickets..."
              className="mt-1 block w-full rounded-md border-0 px-3 py-2 text-sm ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-brand-600"
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
            />
            {state.fieldErrors.question && (
              <p className="mt-1 text-sm text-red-700">{state.fieldErrors.question}</p>
            )}
          </div>
          <VoiceRecorder
            label="Speak question"
            onComplete={() => window.setTimeout(() => formRef.current?.requestSubmit(), 50)}
            onTranscript={(text) => {
              const box = questionRef.current;
              if (box) box.value = box.value ? box.value + " " + text : text;
            }}
          />
          <div className="flex justify-end">
            <button type="submit" disabled={pending} className={buttonClass("primary")}>
              {pending ? "Thinking…" : "Ask assistant"}
            </button>
          </div>
        </form>
      </Card>
      {state.answer && (
        <Card className="p-5">
          <h2 className="text-base font-semibold text-slate-900">Answer</h2>
          <p className="mt-2 whitespace-pre-line text-sm text-slate-800">{state.answer}</p>
          <SpeakButton text={state.answer} />
          {state.links.length > 0 && (
            <ul className="mt-3 flex flex-wrap gap-3 text-sm">
              {state.links.map((link) => (
                <li key={link}>
                  <Link href={link} className="font-medium text-brand-700 hover:underline">
                    Open record
                  </Link>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-3 text-xs text-slate-500">
            Read-only advice. Nothing is sent to the customer automatically.
          </p>
        </Card>
      )}
    </div>
  );
}