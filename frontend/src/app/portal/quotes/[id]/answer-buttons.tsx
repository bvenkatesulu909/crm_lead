"use client";

import { ActionDialog, DialogField } from "@/components/action-dialog";
import type { DialogState } from "@/lib/dialog-state";
import { initialDialogState } from "@/lib/dialog-state";

type Action = (state: DialogState, formData: FormData) => Promise<DialogState>;

/** Accept or decline a quote (each asks for confirmation first). */
export function AnswerButtons({
  accept,
  decline,
}: {
  accept: Action;
  decline: Action;
}) {
  return (
    <div role="group" aria-label="Answer this quote" className="flex flex-wrap gap-2">
      <ActionDialog triggerLabel="Accept quote" triggerVariant="primary" title="Accept this quote?"
        description="We will prepare your order based on this quote and confirm it with you."
        confirmLabel="Accept quote" action={accept} initialState={initialDialogState}>
        {(errors) => (
          <DialogField id="accept-note" label="Message for us" optional error={errors.note} hint="e.g. your purchase order number">
            {(p) => <input name="note" maxLength={500} {...p} />}
          </DialogField>
        )}
      </ActionDialog>
      <ActionDialog triggerLabel="Decline" title="Decline this quote?" description="Please tell us why - we may be able to make a better offer."
        confirmLabel="Decline quote" confirmVariant="danger" action={decline} initialState={initialDialogState}>
        {(errors) => (
          <DialogField id="decline-reason" label="Reason" error={errors.reason}>
            {(p) => <textarea name="reason" rows={3} maxLength={500} {...p} />}
          </DialogField>
        )}
      </ActionDialog>
    </div>
  ); // prettier-ignore
}
