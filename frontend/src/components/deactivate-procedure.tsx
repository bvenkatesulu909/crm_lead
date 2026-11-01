"use client";

import { useActionState } from "react";

import { ErrorAlert, buttonClass } from "@/components/ui";
import { initialDialogState, type DialogState } from "@/lib/dialog-state";

/** Switches the procedure off (it stays in the history). Until a new one is saved the Qualifier
 * does nothing. Administrators only; the API checks again and the version must be current. */
export function DeactivateProcedure({
  action,
}: {
  action: (state: DialogState) => Promise<DialogState>;
}) {
  const [state, formAction, pending] = useActionState(
    action,
    initialDialogState,
  );
  return (
    <form action={formAction} className="space-y-2">
      {state.error && (
        <ErrorAlert title="It could not be switched off" error={state.error} />
      )}
      <button
        type="submit"
        disabled={pending}
        className={buttonClass("secondary")}
      >
        {pending ? "Switching off…" : "Switch the procedure off"}
      </button>
    </form>
  );
}
