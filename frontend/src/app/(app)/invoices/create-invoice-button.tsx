"use client";

import { ActionDialog } from "@/components/action-dialog";
import { type DialogState, initialDialogState } from "@/lib/dialog-state";

/** "Create invoice" on a confirmed order: makes a DRAFT the user then checks and issues. */
export function CreateInvoiceButton({
  action,
}: {
  action: (state: DialogState, formData: FormData) => Promise<DialogState>;
}) {
  return (
    <ActionDialog
      triggerLabel="Create invoice"
      title="Create an invoice for this order?"
      description="A draft invoice is created with the order's lines and amounts. It gets a number and becomes visible to the customer only when you issue it."
      confirmLabel="Create draft invoice"
      action={action}
      initialState={initialDialogState}
    />
  );
}
