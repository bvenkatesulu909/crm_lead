"use client";

import { useActionState } from "react";

import { ErrorAlert, buttonClass } from "@/components/ui";
import { initialDialogState, type DialogState } from "@/lib/dialog-state";

type Action = (state: DialogState) => Promise<DialogState>;

/**
 * "Ask the lead agent": it judges this lead by the organisation's written qualification steps
 * (with any web evidence and possible duplicates) and may suggest a new status. It only suggests - a different person approves what it proposes. The
 * API reports when it is switched off, over budget or over a limit; the words come from the
 * server action.
 */
export function AskLeadAgentButton({ action }: { action: Action }) {
  const [state, formAction, pending] = useActionState(
    action,
    initialDialogState,
  );
  return (
    <form action={formAction} className="space-y-3">
      {state.error && (
        <ErrorAlert
          title="The lead agent could not look at this lead"
          error={state.error}
        />
      )}
      <button
        type="submit"
        disabled={pending}
        className={buttonClass("secondary")}
      >
        {pending ? "Looking…" : "Ask the lead agent"}
      </button>
      <p className="text-xs text-slate-500">
        Judges this lead by your organisation&apos;s qualification steps, with
        any web evidence on file and possible duplicates, and may suggest a new
        status. Nothing changes until a different person approves it.
      </p>
    </form>
  );
}
