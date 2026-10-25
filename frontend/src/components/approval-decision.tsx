"use client";

import { ActionDialog, DialogField } from "@/components/action-dialog";
import { type DialogState, initialDialogState } from "@/lib/dialog-state";

type BoundAction = (
  state: DialogState,
  formData: FormData,
) => Promise<DialogState>;

/**
 * Approve / Reject for one waiting proposal. Both open a confirmation dialog first; approving
 * says what will happen, rejecting asks for a note so the colleague knows why.
 */
export function ApprovalDecision({
  description,
  approve,
  reject,
}: {
  /** What the proposal would do, shown in the confirmation. */
  description: string;
  approve: BoundAction;
  reject: BoundAction;
}) {
  return (
    <>
      <ActionDialog
        triggerLabel="Reject"
        triggerVariant="secondary"
        title="Reject this proposal?"
        description={
          <>
            Nothing will change. The colleague who asked is told why:{" "}
            {description}.
          </>
        }
        confirmLabel="Reject proposal"
        confirmVariant="danger"
        action={reject}
        initialState={initialDialogState}
      >
        {(errors) => (
          <DialogField id="reject-note" label="Why?" error={errors.note}>
            {(props) => (
              <textarea name="note" rows={3} maxLength={500} {...props} />
            )}
          </DialogField>
        )}
      </ActionDialog>
      <ActionDialog
        triggerLabel="Approve"
        triggerVariant="primary"
        title="Approve this proposal?"
        description={
          <>
            It runs now, with your rights, and is recorded in the history:{" "}
            {description}.
          </>
        }
        confirmLabel="Approve and run"
        action={approve}
        initialState={initialDialogState}
      >
        {(errors) => (
          <DialogField
            id="approve-note"
            label="Note"
            optional
            error={errors.note}
          >
            {(props) => (
              <textarea name="note" rows={2} maxLength={500} {...props} />
            )}
          </DialogField>
        )}
      </ActionDialog>
    </>
  );
}
