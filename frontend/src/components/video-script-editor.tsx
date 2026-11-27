"use client";

import { useActionState, useId, useState } from "react";

import { ErrorAlert, buttonClass } from "@/components/ui";
import type { VideoBrief } from "@/lib/api-types";
import { initialDialogState, type DialogState } from "@/lib/dialog-state";
import { countWords, wordTarget } from "@/lib/video-scripts";

type SaveAction = (
  leadId: string,
  previous: DialogState,
  formData: FormData,
) => Promise<DialogState>;

const FIELD =
  "mt-1 block w-full rounded-md border-0 bg-white px-3 py-2 text-sm ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-brand-600";

/**
 * Write your own script for the buyer video and keep it (ADR 0041, VB3). It starts from the script
 * the CRM suggests; everything is plain text. The goal, language, tone and length are the ones the
 * brief above was built for - they travel as hidden fields, never as editable ones. The API cleans
 * the text and refuses what must not be said; after a refusal the typed text stays.
 */
export function VideoScriptEditor({
  leadId,
  brief,
  action,
  initialText,
  quoteId = "",
}: {
  leadId: string;
  brief: VideoBrief;
  action: SaveAction;
  initialText: string;
  quoteId?: string;
}) {
  const [state, formAction, pending] = useActionState(
    action.bind(null, leadId),
    initialDialogState,
  );
  // The text is kept in state and the field remounts with it after each attempt, because React
  // clears an uncontrolled field when a form action ends.
  const [text, setText] = useState(initialText);
  const id = useId();
  const words = countWords(text);
  const target = wordTarget(brief.length_seconds);
  return (
    <form action={formAction} className="space-y-3 print:hidden">
      <h2 className="text-lg font-semibold">Write your own script</h2>
      {state.error && <ErrorAlert title="Could not save" error={state.error} />}
      <input type="hidden" name="goal" value={brief.goal} />
      <input type="hidden" name="language" value={brief.language} />
      <input type="hidden" name="tone" value={brief.tone} />
      <input type="hidden" name="length" value={brief.length_seconds} />
      <input type="hidden" name="quote_id" value={quoteId} />
      <div>
        <label htmlFor={`${id}-lines`} className="text-sm font-medium">
          Your script (one sentence on each line)
        </label>
        <textarea
          id={`${id}-lines`}
          name="lines"
          key={state.attempt}
          rows={10}
          lang={brief.language}
          defaultValue={text}
          onChange={(e) => setText(e.target.value)}
          className={FIELD}
        />
        <p
          className={`mt-1 text-xs ${words > target ? "font-medium text-red-700" : "text-slate-600"}`}
        >
          {words} words; {brief.length_seconds} seconds holds about {target}.
        </p>
        {state.fieldErrors.lines && (
          <p className="mt-1 text-xs text-red-700">{state.fieldErrors.lines}</p>
        )}
      </div>
      <p className="text-xs text-slate-500">
        Saving keeps a new version. Links are taken out; card numbers, phone
        numbers, e-mail addresses and anything on the never-say list are
        refused.
      </p>
      <button type="submit" disabled={pending} className={buttonClass()}>
        {pending ? "Saving…" : "Save script"}
      </button>
    </form>
  );
}
