"use client";

import Link from "next/link";
import { useState } from "react";

import { ActionDialog, DialogField } from "@/components/action-dialog";
import { AccountPicker } from "@/components/account-picker";
import { buttonClass } from "@/components/ui";
import type { DirectoryUser } from "@/lib/api-types";
import { type DialogState, initialDialogState } from "@/lib/dialog-state";
import type { LeadActions } from "@/lib/lead-rules";

type BoundAction = (
  state: DialogState,
  formData: FormData,
) => Promise<DialogState>;

export type LeadSummary = {
  id: string;
  name: string;
  company: string | null;
  ownerId: string | null;
  ownerName: string;
};

/**
 * The buttons on a lead page. Every change opens a confirmation dialog first.
 * Which buttons appear is a display decision only (lib/lead-rules.ts); the API decides.
 */
export function LeadActionBar({
  lead,
  can,
  assignees,
  hasAccounts,
  actions,
}: {
  lead: LeadSummary;
  can: LeadActions;
  assignees: DirectoryUser[];
  /** Whether this user can link a lead to an existing account (the picker searches them). */
  hasAccounts: boolean;
  actions: {
    assign: BoundAction;
    markContacted: BoundAction;
    qualify: BoundAction;
    disqualify: BoundAction;
    convert: BoundAction;
  };
}) {
  const anything = Object.values(can).some(Boolean);
  if (!anything) return null;

  return (
    <div
      role="group"
      aria-label="Lead actions"
      className="flex flex-wrap gap-2"
    >
      {can.edit && (
        <Link
          href={`/leads/${lead.id}/edit`}
          className={buttonClass("secondary")}
        >
          Edit
        </Link>
      )}

      {can.assign && (
        <ActionDialog
          triggerLabel="Assign"
          title="Assign this lead"
          description={
            <>
              <strong>{lead.name}</strong> is owned by{" "}
              <strong>{lead.ownerName}</strong>. The new owner will see and
              manage it; the current owner may lose access. The change is
              recorded in the assignment history.
            </>
          }
          confirmLabel="Assign lead"
          action={actions.assign}
          initialState={initialDialogState}
        >
          {(errors) => (
            <>
              <DialogField
                id="assign-owner"
                label="New owner"
                error={errors.owner_id}
              >
                {(props) => (
                  <select name="owner_id" defaultValue="" {...props}>
                    <option value="" disabled>
                      Choose a sales employee…
                    </option>
                    {assignees
                      .filter((u) => u.id !== lead.ownerId)
                      .map((u) => (
                        <option key={u.id} value={u.id}>
                          {u.display_name}
                        </option>
                      ))}
                  </select>
                )}
              </DialogField>
              <DialogField
                id="assign-reason"
                label="Reason"
                optional
                error={errors.reason}
              >
                {(props) => <input name="reason" maxLength={500} {...props} />}
              </DialogField>
            </>
          )}
        </ActionDialog>
      )}

      {can.markContacted && (
        <ActionDialog
          triggerLabel="Mark as contacted"
          title="Mark as contacted?"
          description="Use this when you have been in touch with this lead."
          confirmLabel="Mark as contacted"
          action={actions.markContacted}
          initialState={initialDialogState}
        />
      )}

      {can.qualify && (
        <ActionDialog
          triggerLabel="Qualify"
          triggerVariant="primary"
          title="Qualify this lead?"
          description="A qualified lead is a real sales opportunity and can then be converted."
          confirmLabel="Qualify lead"
          action={actions.qualify}
          initialState={initialDialogState}
        >
          {(errors) => (
            <DialogField
              id="qualify-reason"
              label="Note"
              optional
              error={errors.reason}
            >
              {(props) => (
                <input
                  name="reason"
                  maxLength={500}
                  placeholder="e.g. Budget confirmed"
                  {...props}
                />
              )}
            </DialogField>
          )}
        </ActionDialog>
      )}

      {can.disqualify && (
        <ActionDialog
          triggerLabel="Disqualify"
          triggerVariant="danger"
          title="Disqualify this lead?"
          description="The lead is marked as not a fit. It can be reopened later by marking it as contacted."
          confirmLabel="Disqualify lead"
          confirmVariant="danger"
          action={actions.disqualify}
          initialState={initialDialogState}
        >
          {(errors) => (
            <DialogField
              id="disqualify-reason"
              label="Reason"
              error={errors.reason}
            >
              {(props) => (
                <textarea
                  name="reason"
                  rows={3}
                  maxLength={500}
                  required
                  {...props}
                />
              )}
            </DialogField>
          )}
        </ActionDialog>
      )}

      {can.convert && (
        <ConvertDialog
          lead={lead}
          hasAccounts={hasAccounts}
          action={actions.convert}
        />
      )}
    </div>
  );
}

function ConvertDialog({
  lead,
  hasAccounts,
  action,
}: {
  lead: LeadSummary;
  hasAccounts: boolean;
  action: BoundAction;
}) {
  const [mode, setMode] = useState<"new" | "existing">("new");
  const [withOpportunity, setWithOpportunity] = useState(true);

  return (
    <ActionDialog
      triggerLabel="Convert"
      triggerVariant="primary"
      title="Convert this lead"
      description={
        <>
          This creates a <strong>contact</strong> for {lead.name}, links it to an{" "}
          <strong>account</strong> and can create an <strong>opportunity</strong> — all at once.
          The lead then becomes read-only. <strong>This cannot be undone.</strong>
        </>
      }
      confirmLabel="Convert lead"
      action={action}
      initialState={initialDialogState}
    >
      {(errors) => (
        <>
          <fieldset>
            <legend className="text-sm font-medium text-slate-700">Account</legend>
            <div className="mt-2 space-y-2 text-sm">
              <label className="flex items-center gap-2">
                <input type="radio" name="account_mode" value="new" checked={mode === "new"}
                  onChange={() => setMode("new")} />
                Create a new account
              </label>
              <label className="flex items-center gap-2">
                <input type="radio" name="account_mode" value="existing" checked={mode === "existing"}
                  onChange={() => setMode("existing")} disabled={!hasAccounts} />
                Link to an existing account{!hasAccounts && " (none available to you)"}
              </label>
            </div>
          </fieldset>
          {mode === "new" ? (
            <DialogField id="convert-account-name" label="Account name" optional
              hint={`Defaults to "${lead.company ?? lead.name}"`} error={errors.account_name}>
              {(props) => <input name="account_name" maxLength={255} {...props} />}
            </DialogField>
          ) : (
            <DialogField id="convert-account" label="Existing account" error={errors.existing_account_id}>
              {(props) => (
                <AccountPicker {...props} name="existing_account_id" labelName="existing_account_label" />
              )}
            </DialogField>
          )}

          <label className="flex items-center gap-2 text-sm font-medium text-slate-700">
            <input type="checkbox" name="create_opportunity" checked={withOpportunity}
              onChange={(e) => setWithOpportunity(e.target.checked)} />
            Also create an opportunity
          </label>
          {withOpportunity && (
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <DialogField id="convert-opp-name" label="Opportunity name" optional error={errors.opportunity_name}>
                  {(props) => <input name="opportunity_name" maxLength={255} {...props} />}
                </DialogField>
              </div>
              <DialogField id="convert-amount" label="Amount" optional error={errors.amount}>
                {(props) => <input name="amount" inputMode="decimal" placeholder="25000.00" {...props} />}
              </DialogField>
              <DialogField id="convert-currency" label="Currency" hint="3 letters, e.g. EUR" error={errors.currency}>
                {(props) => <input name="currency" defaultValue="EUR" maxLength={3} {...props} />}
              </DialogField>
              <DialogField id="convert-close" label="Expected close date" optional error={errors.expected_close_date}>
                {(props) => <input name="expected_close_date" type="date" {...props} />}
              </DialogField>
            </div>
          )}
        </>
      )}
    </ActionDialog>
  ); // prettier-ignore
}
