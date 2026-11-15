"use client";

import { useActionState } from "react";

import { ErrorAlert, buttonClass } from "@/components/ui";
import { initialDialogState, type DialogState } from "@/lib/dialog-state";

type Action = (state: DialogState) => Promise<DialogState>;

/**
 * "Review this deal": three AI reviewers look at the deal at the same time and a desk lead writes
 * a short brief. It may suggest at most two follow-up tasks; a different person approves them.
 * The API reports when it is switched off, over budget or over a limit.
 */
export function AskDealDeskButton({ action }: { action: Action }) {
  const [state, formAction, pending] = useActionState(
    action,
    initialDialogState,
  );
  return (
    <form action={formAction} className="space-y-3">
      {state.error && (
        <ErrorAlert
          title="The deal desk could not review this deal"
          error={state.error}
        />
      )}
      <button
        type="submit"
        disabled={pending}
        className={buttonClass("secondary")}
      >
        {pending ? "Reviewing…" : "Review this deal"}
      </button>
      <p className="text-xs text-slate-500">
        Three AI reviewers look at pricing, the account and the deal&apos;s
        momentum. Any task they suggest waits for a different person to approve
        it; nothing on the deal changes by itself.
      </p>
    </form>
  );
}
