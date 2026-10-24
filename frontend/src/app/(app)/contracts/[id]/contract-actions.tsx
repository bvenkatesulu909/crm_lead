"use client";

import { ActionDialog, DialogField } from "@/components/action-dialog";
import { ButtonLink } from "@/components/ui";
import type { ContractStatus } from "@/lib/api-types";
import type { DialogState } from "@/lib/dialog-state";
import { initialDialogState } from "@/lib/dialog-state";

type Action = (state: DialogState, formData: FormData) => Promise<DialogState>;

/**
 * Buttons for the contract's next steps. Which buttons appear is display only - the API checks
 * permissions, the version and the status flow again.
 */
export function ContractActions({
  id,
  status,
  hasRenewal,
  can,
  act,
}: {
  id: string;
  status: ContractStatus;
  /** A renewal (draft or later) already exists, so another one can't be made. */
  hasRenewal: boolean;
  can: { write: boolean; manage: boolean };
  act: Record<"activate" | "terminate" | "renew" | "note", Action>;
}) {
  const note = (fieldId: string, label = "Note") =>
    function NoteField(errors: Record<string, string>) {
      return (
        <DialogField id={fieldId} label={label} optional error={errors.note}>
          {(p) => <input name="note" maxLength={500} {...p} />}
        </DialogField>
      );
    };
  return (
    <div role="group" aria-label="Contract actions" className="flex flex-wrap gap-2">
      {(status === "draft" || status === "active") && can.write && (
        <ButtonLink href={`/contracts/${id}/edit`} variant="secondary">Edit</ButtonLink>
      )}
      {status === "draft" && can.manage && (
        <ActionDialog triggerLabel="Activate" triggerVariant="primary" title="Activate this contract?"
          description="It needs a start and an end date. From then on its dates and value are fixed (change them by renewing), and the owner is reminded before it ends. A renewal replaces the contract it renews."
          confirmLabel="Activate" action={act.activate} initialState={initialDialogState}>
          {note("activate-note")}
        </ActionDialog>
      )}
      {(status === "active" || status === "expired") && can.manage && !hasRenewal && (
        <ActionDialog triggerLabel="Renew" triggerVariant={status === "expired" ? "primary" : "secondary"} title="Renew this contract?"
          description="A new draft is created with the same account, terms and value. Leave the dates empty to start the day after this one ends. Activate the draft to complete the renewal."
          confirmLabel="Create renewal" action={act.renew} initialState={initialDialogState}>
          {(errors) => (
            <>
              <DialogField id="renew-start" label="Start date" optional error={errors.start_date}>
                {(p) => <input type="date" name="start_date" {...p} />}
              </DialogField>
              <DialogField id="renew-end" label="End date" optional error={errors.end_date}>
                {(p) => <input type="date" name="end_date" {...p} />}
              </DialogField>
              <DialogField id="renew-value" label="Total value" optional error={errors.total_value} hint="Empty = the same value as now.">
                {(p) => <input name="total_value" inputMode="decimal" {...p} />}
              </DialogField>
              {note("renew-note")(errors)}
            </>
          )}
        </ActionDialog>
      )}
      {status === "active" && can.manage && (
        <ActionDialog triggerLabel="Terminate" title="End this contract early?"
          description="The contract is marked terminated and cannot be changed or renewed afterwards. The reason is kept in the history."
          confirmLabel="Terminate" confirmVariant="danger" action={act.terminate} initialState={initialDialogState}>
          {(errors) => (
            <DialogField id="terminate-reason" label="Reason" error={errors.reason}>
              {(p) => <textarea name="reason" rows={3} maxLength={500} placeholder="e.g. The customer moved to another provider" {...p} />}
            </DialogField>
          )}
        </ActionDialog>
      )}
      {can.write && (
        <ActionDialog triggerLabel="Add note" title="Add a note to the history"
          description="Notes are visible to everyone who can see this contract."
          confirmLabel="Add note" action={act.note} initialState={initialDialogState}>
          {(errors) => (
            <DialogField id="note-text" label="Note" error={errors.note}>
              {(p) => <textarea name="note" rows={3} maxLength={500} {...p} />}
            </DialogField>
          )}
        </ActionDialog>
      )}
    </div>
  ); // prettier-ignore
}
