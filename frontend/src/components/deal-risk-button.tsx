"use client";

import { useActionState } from "react";

import { ErrorAlert, buttonClass } from "@/components/ui";
import { initialDialogState, type DialogState } from "@/lib/dialog-state";

type Action = (state: DialogState) => Promise<DialogState>;

/** "Update forecast": works the forecast out again from the CRM's records. No AI is involved. */
export function UpdateDealRiskButton({
  action,
  hasForecast,
}: {
  action: Action;
  hasForecast: boolean;
}) {
  const [state, formAction, pending] = useActionState(
    action,
    initialDialogState,
  );
  return (
    <form action={formAction} className="space-y-3">
      {state.error && (
        <ErrorAlert
          title="The forecast could not be updated"
          error={state.error}
        />
      )}
      <button
        type="submit"
        disabled={pending}
        className={buttonClass("secondary")}
      >
        {pending
          ? "Working it out…"
          : hasForecast
            ? "Update forecast"
            : "Work out the forecast"}
      </button>
    </form>
  );
}
