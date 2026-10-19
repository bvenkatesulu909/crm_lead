"use client";

import { ActionDialog } from "@/components/action-dialog";
import type { DialogState } from "@/lib/dialog-state";
import { initialDialogState } from "@/lib/dialog-state";

export function DeleteRuleButton({
  action,
  name,
}: {
  action: (state: DialogState, formData: FormData) => Promise<DialogState>;
  name: string;
}) {
  return (
    <ActionDialog triggerLabel="Delete rule" triggerVariant="secondary" title={`Delete "${name}"?`}
      description="The rule stops at once and its run log is deleted with it. What it already did (tasks, notifications, changes) stays."
      confirmLabel="Delete" confirmVariant="danger" action={action} initialState={initialDialogState} />
  ); // prettier-ignore
}
