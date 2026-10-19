"use client";

import { ActionDialog, DialogField } from "@/components/action-dialog";
import { ButtonLink } from "@/components/ui";
import type { DialogState } from "@/lib/dialog-state";
import { initialDialogState } from "@/lib/dialog-state";

/** Edit and archive buttons for a contact (display only; the API checks every change). */
export function ContactActions({
  contactId,
  archive,
}: {
  contactId: string;
  archive: (state: DialogState, formData: FormData) => Promise<DialogState>;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      <ButtonLink href={`/contacts/${contactId}/edit`}>Edit</ButtonLink>
      <ActionDialog
        triggerLabel="Archive"
        triggerVariant="danger"
        title="Archive this contact?"
        description="The contact disappears from lists and from the account. Nothing is deleted and the change history is kept."
        confirmLabel="Archive contact"
        confirmVariant="danger"
        action={archive}
        initialState={initialDialogState}
      >
        {(errors) => (
          <DialogField
            id="contact-archive-reason"
            label="Reason"
            optional
            hint="For example: left the company."
            error={errors.reason}
          >
            {(p) => <textarea name="reason" rows={3} maxLength={500} {...p} />}
          </DialogField>
        )}
      </ActionDialog>
    </div>
  );
}
