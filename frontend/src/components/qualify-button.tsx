"use client";

import { useActionState } from "react";

import { ErrorAlert, buttonClass } from "@/components/ui";
import { initialDialogState, type DialogState } from "@/lib/dialog-state";

type Action = (state: DialogState) => Promise<DialogState>;

/**
 * "Qualify": asks the Qualifier to assess this lead. It only suggests - a different person
 * approves what it proposes. The API reports when it is switched off, over budget or over a limit;
 * the words come from the server action.
 */
export function QualifyButton({ action }: { action: Action }) {
  const [state, formAction, pending] = useActionState(
    action,
    initialDialogState,
  );
  return (
    <form action={formAction} className="space-y-3">
      {state.error && (
        <ErrorAlert
          title="The lead could not be assessed"
          error={state.error}
        />
      )}
      <button
        type="submit"
        disabled={pending}
        className={buttonClass("primary")}
      >
        {pending ? "Assessing…" : "Qualify"}
      </button>
      <p className="text-xs text-slate-500">
        Reads this lead and your organisation&apos;s written steps and suggests
        what to do. Nothing changes until a different person approves it.
      </p>
    </form>
  );
}
