"use client";

import { ActionDialog } from "@/components/action-dialog";
import type { DialogState } from "@/lib/dialog-state";
import { initialDialogState } from "@/lib/dialog-state";

export function RestoreButton({
  name,
  restore,
}: {
  name: string;
  restore: (state: DialogState, formData: FormData) => Promise<DialogState>;
}) {
  return (
    <ActionDialog
      triggerLabel="Restore"
      title={`Restore ${name}?`}
      description="The account comes back to the account list with all its history. It stays inactive until someone reactivates it."
      confirmLabel="Restore account"
      action={restore}
      initialState={initialDialogState}
    />
  );
}
