"use client";

import { useId } from "react";

import { ActionDialog, DialogField } from "@/components/action-dialog";
import type { DialogState } from "@/lib/dialog-state";
import { initialDialogState } from "@/lib/dialog-state";

type Action = (state: DialogState, formData: FormData) => Promise<DialogState>;

/** Done / Cancel / Reopen for one activity. Each asks for confirmation first. */
export function ActivityButtons({
  subject,
  status,
  complete,
  cancel,
  reopen,
}: {
  subject: string;
  status: "open" | "done" | "cancelled";
  complete?: Action;
  cancel?: Action;
  reopen?: Action;
}) {
  // Unique per task: many of these dialogs can be on one page.
  const outcomeId = useId();
  if (status !== "open")
    return reopen ? (
      <ActionDialog
        triggerLabel="Reopen"
        title={`Reopen "${subject}"?`}
        description="It goes back to the open tasks."
        confirmLabel="Reopen"
        action={reopen}
        initialState={initialDialogState}
      />
    ) : null;
  return (
    <div className="flex flex-wrap gap-2">
      {complete && (
        <ActionDialog triggerLabel="Done" triggerVariant="primary" title={`Mark "${subject}" as done?`}
          description="Optionally note the outcome." confirmLabel="Mark as done"
          action={complete} initialState={initialDialogState}>
          {(errors) => (
            <DialogField id={outcomeId} label="Outcome" optional error={errors.outcome}>
              {(p) => <input name="outcome" maxLength={500} placeholder="e.g. Sent the quote" {...p} />}
            </DialogField>
          )}
        </ActionDialog>
      )}
      {cancel && (
        <ActionDialog triggerLabel="Cancel task" title={`Cancel "${subject}"?`}
          description="Use this when it no longer needs doing. It stays in the history."
          confirmLabel="Cancel task" confirmVariant="danger" action={cancel} initialState={initialDialogState} />
      )}
    </div>
  ); // prettier-ignore
}
