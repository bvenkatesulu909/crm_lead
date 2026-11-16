"use client";

import { useActionState } from "react";

import { ErrorAlert, buttonClass } from "@/components/ui";
import { initialDialogState, type DialogState } from "@/lib/dialog-state";

type Action = (state: DialogState) => Promise<DialogState>;

/**
 * Switch a custom agent on or off in the AI agents registry. Switching on is refused by the
 * registry until the current version has had a dry run; the button says so up front, and the
 * registry still decides.
 */
export function SwitchCustomAgent({
  enabled,
  tried,
  onAction,
  offAction,
}: {
  enabled: boolean;
  tried: boolean;
  onAction: Action;
  offAction: Action;
}) {
  const [state, formAction, pending] = useActionState(
    enabled ? offAction : onAction,
    initialDialogState,
  );
  return (
    <form action={formAction} className="space-y-2">
      {state.error && (
        <ErrorAlert title="The switch did not work" error={state.error} />
      )}
      <button
        type="submit"
        disabled={pending || (!enabled && !tried)}
        className={buttonClass(enabled ? "secondary" : "primary")}
      >
        {enabled ? "Switch off" : "Switch on"}
      </button>
      {!enabled && !tried && (
        <p className="text-xs text-slate-500">
          Run a dry run of this version first. Then it can be switched on.
        </p>
      )}
    </form>
  );
}

/** Retire an agent: it can no longer be run or edited; its history stays. Asks first. */
export function RetireCustomAgent({ action }: { action: Action }) {
  const [state, formAction, pending] = useActionState(
    action,
    initialDialogState,
  );
  return (
    <form
      action={formAction}
      onSubmit={(event) => {
        if (
          !window.confirm(
            "Retire this agent? It can no longer be run or edited. Its history stays.",
          )
        )
          event.preventDefault();
      }}
      className="space-y-2"
    >
      {state.error && (
        <ErrorAlert
          title="The agent could not be retired"
          error={state.error}
        />
      )}
      <button
        type="submit"
        disabled={pending}
        className={buttonClass("danger")}
      >
        Retire this agent
      </button>
    </form>
  );
}
