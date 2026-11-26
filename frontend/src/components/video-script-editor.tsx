"use client";

import { useActionState, useId, useState } from "react";

import { ErrorAlert, buttonClass } from "@/components/ui";
import type { VideoBrief } from "@/lib/api-types";
import { initialDialogState, type DialogState } from "@/lib/dialog-state";
import {
  countWords,
  initialDraftState,
  wordTarget,
  type DraftState,
} from "@/lib/video-scripts";

type SaveAction = (
  leadId: string,
  previous: DialogState,
  formData: FormData,
) => Promise<DialogState>;

type DraftAction = (
  leadId: string,
  previous: DraftState,
  formData: FormData,
) => Promise<DraftState>;

const FIELD =
  "mt-1 block w-full rounded-md border-0 bg-white px-3 py-2 text-sm ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-brand-600";

/**
 * Write a script for the buyer video, keep it, ask the drafter for one, or send it to a colleague
 * for approval (ADR 0041, VB3-VB5). It starts from the script the CRM suggests; everything is plain
 * text. The goal, language, tone, length and quote are the ones the brief above was built for - they
 * travel as hidden fields, never as editable ones. A draft only fills the box: it is not saved and
 * not approved, and what is in the box when someone presses a button is what is sent. The server
 * cleans the text and refuses what must not be said; after a refusal the typed text stays.
 */
export function VideoScriptEditor({
  leadId,
  brief,
  action,
  draftAction,
  proposeAction,
  initialText,
  quoteId = "",
}: {
  leadId: string;
  brief: VideoBrief;
  action: SaveAction;
  draftAction: DraftAction;
  proposeAction: SaveAction;
  initialText: string;
  quoteId?: string;
}) {
  const [state, saveForm, saving] = useActionState(
    action.bind(null, leadId),
    initialDialogState,
  );
  const [drafted, draftForm, drafting] = useActionState(
    draftAction.bind(null, leadId),
    initialDraftState,
  );
  const [proposed, proposeForm, proposing] = useActionState(
    proposeAction.bind(null, leadId),
    initialDialogState,
  );
  // The box is controlled: its text survives every refused action, and a draft can fill it.
  const [text, setText] = useState(initialText);
  // A new draft fills the box. State is adjusted while rendering (React's own pattern for this),
  // not in an effect, so the box never shows the old text for a moment.
  const [seenDraft, setSeenDraft] = useState(drafted);
  if (drafted !== seenDraft) {
    setSeenDraft(drafted);
    if (drafted.draft) setText(drafted.draft.lines.join("\n"));
  }
  const id = useId();
  const words = countWords(text);
  const target = wordTarget(brief.length_seconds);
  const busy = saving || drafting || proposing;
  const error = state.error ?? drafted.error ?? proposed.error;
  const lineError =
    state.fieldErrors.lines ?? proposed.fieldErrors.lines ?? undefined;
  return (
    <form className="space-y-3 print:hidden">
      <h2 className="text-lg font-semibold">Write your own script</h2>
      {error && <ErrorAlert title="Could not do that" error={error} />}
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
          rows={10}
          lang={brief.language}
          value={text}
          onChange={(e) => setText(e.target.value)}
          className={FIELD}
        />
        <p
          className={`mt-1 text-xs ${words > target ? "font-medium text-red-700" : "text-slate-600"}`}
        >
          {words} words; {brief.length_seconds} seconds holds about {target}.
        </p>
        {lineError && <p className="mt-1 text-xs text-red-700">{lineError}</p>}
        {drafted.draft && (
          <p className="mt-2 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-900">
            AI draft - not saved and not approved. Read it, change what you
            like, then save it yourself or send it for approval. Based on:{" "}
            {drafted.draft.reason}
          </p>
        )}
      </div>
      <p className="text-xs text-slate-500">
        Saving keeps a new version. Links are taken out; card numbers, phone
        numbers, e-mail addresses and anything on the never-say list are
        refused. A script sent for approval is saved only when a colleague
        approves it.
      </p>
      <div className="flex flex-wrap gap-2">
        <button
          type="submit"
          formAction={saveForm}
          disabled={busy}
          className={buttonClass()}
        >
          {saving ? "Saving…" : "Save script"}
        </button>
        <button
          type="submit"
          formAction={draftForm}
          disabled={busy}
          className={buttonClass("secondary")}
        >
          {drafting ? "Drafting…" : "Draft with AI"}
        </button>
        <button
          type="submit"
          formAction={proposeForm}
          disabled={busy}
          className={buttonClass("secondary")}
        >
          {proposing ? "Sending…" : "Send for approval"}
        </button>
      </div>
    </form>
  );
}
