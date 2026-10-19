"use client";

import { ActionDialog, DialogField } from "@/components/action-dialog";
import { ButtonLink } from "@/components/ui";
import type { DialogState } from "@/lib/dialog-state";
import { initialDialogState } from "@/lib/dialog-state";

type Action = (state: DialogState, formData: FormData) => Promise<DialogState>;

/**
 * Buttons for changing an account. Which buttons appear is a display decision only; every
 * action is checked again by the API.
 */
export function AccountActions({
  accountId,
  status,
  canEdit,
  canArchive,
  changeStatus,
  archive,
  transfer,
}: {
  accountId: string;
  status: "active" | "inactive";
  canEdit: boolean;
  canArchive: boolean;
  changeStatus: Action;
  archive: Action;
  /** Managers only: hand the customer to another sales employee. */
  transfer?: { action: Action; owners: { id: string; name: string }[] };
}) {
  if (!canEdit) return null;
  return (
    <div className="flex flex-wrap gap-2">
      <ButtonLink href={`/accounts/${accountId}/edit`}>Edit</ButtonLink>
      {status === "active" ? (
        <ActionDialog
          triggerLabel="Deactivate"
          title="Deactivate this account?"
          description="The account stays visible with all its history, marked as inactive. You can reactivate it at any time."
          confirmLabel="Deactivate"
          confirmVariant="danger"
          action={changeStatus}
          initialState={initialDialogState}
        >
          {(errors) => (
            <DialogField id="deactivate-reason" label="Reason" optional error={errors.reason}>
              {(p) => <textarea name="reason" rows={3} maxLength={500} {...p} />}
            </DialogField>
          )}
        </ActionDialog>
      ) : (
        <ActionDialog
          triggerLabel="Reactivate"
          title="Reactivate this account?"
          description="The account becomes active again."
          confirmLabel="Reactivate"
          action={changeStatus}
          initialState={initialDialogState}
        >
          {(errors) => (
            <DialogField id="activate-reason" label="Reason" optional error={errors.reason}>
              {(p) => <textarea name="reason" rows={3} maxLength={500} {...p} />}
            </DialogField>
          )}
        </ActionDialog>
      )}
      {transfer && (
        <ActionDialog
          triggerLabel="Transfer customer"
          title="Transfer this customer to a colleague"
          description="The new owner takes over the relationship. By default the previous owner's contacts, open deals and open tasks on this customer move too. The reason is kept in the history."
          confirmLabel="Transfer"
          action={transfer.action}
          initialState={initialDialogState}
        >
          {(errors) => (
            <>
              <DialogField id="transfer-owner" label="New owner" error={errors.new_owner_id}>
                {(p) => (
                  <select name="new_owner_id" defaultValue="" {...p}>
                    <option value="" disabled>Choose…</option>
                    {transfer.owners.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
                  </select>
                )}
              </DialogField>
              <DialogField id="transfer-reason" label="Reason" error={errors.reason}>
                {(p) => <textarea name="reason" rows={2} maxLength={500} placeholder="e.g. Territory change" {...p} />}
              </DialogField>
              <fieldset className="space-y-1 text-sm text-slate-700">
                <legend className="font-medium">Also move the previous owner&apos;s…</legend>
                {([["include_contacts", "contacts at this customer"], ["include_open_opportunities", "open deals"],
                   ["include_open_tasks", "open tasks and follow-ups"]] as const).map(([name, label]) => (
                  <label key={name} className="flex items-center gap-2">
                    <input type="checkbox" name={name} defaultChecked /> {label}
                  </label>
                ))}
              </fieldset>
            </>
          )}
        </ActionDialog>
      )}
      {canArchive && status === "inactive" && (
        <ActionDialog
          triggerLabel="Archive"
          triggerVariant="danger"
          title="Archive this account?"
          description="The account disappears from lists and screens. Nothing is deleted: managers can restore it from Accounts → Archived. Accounts that still have child accounts cannot be archived."
          confirmLabel="Archive account"
          confirmVariant="danger"
          action={archive}
          initialState={initialDialogState}
        >
          {(errors) => (
            <DialogField id="archive-reason" label="Reason" error={errors.reason}>
              {(p) => <textarea name="reason" rows={3} maxLength={500} required {...p} />}
            </DialogField>
          )}
        </ActionDialog>
      )}
    </div>
  ); // prettier-ignore
}
