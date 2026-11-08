"use client";

import { useActionState } from "react";

import { ErrorAlert, buttonClass } from "@/components/ui";
import { initialDialogState, type DialogState } from "@/lib/dialog-state";

type Action = (state: DialogState) => Promise<DialogState>;

/** "Research this account": a one-page brief from the CRM's own records. It reads only and
 * proposes nothing. */
export function ResearchButton({ action }: { action: Action }) {
  const [state, formAction, pending] = useActionState(
    action,
    initialDialogState,
  );
  return (
    <form action={formAction} className="space-y-3">
      {state.error && (
        <ErrorAlert
          title="The brief could not be written"
          error={state.error}
        />
      )}
      <button
        type="submit"
        disabled={pending}
        className={buttonClass("secondary")}
      >
        {pending ? "Writing…" : "Research this account"}
      </button>
      <p className="text-xs text-slate-500">
        Reads this account&apos;s deals, support, interactions and the registry
        checks on file - only what you may see - and writes a short brief. Every
        sentence names its source. It changes nothing.
      </p>
    </form>
  );
}
