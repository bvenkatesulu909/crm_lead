"use client";

import { ActionDialog, DialogField } from "@/components/action-dialog";
import { ButtonLink } from "@/components/ui";
import { OPEN_STAGES, type Stage } from "@/lib/api-types";
import type { DialogState } from "@/lib/dialog-state";
import { initialDialogState } from "@/lib/dialog-state";
import { STAGE_LABELS } from "@/lib/pipeline";

type Action = (state: DialogState, formData: FormData) => Promise<DialogState>;

/** Buttons for one deal (display only; the API checks every action again). */
export function OpportunityActions({
  id,
  stage,
  hasAmount,
  canEdit,
  canReopen,
  actions,
}: {
  id: string;
  stage: Stage;
  hasAmount: boolean;
  canEdit: boolean;
  canReopen: boolean;
  actions: { move: Action; won: Action; lost: Action; reopen: Action };
}) {
  const closed = stage === "closed_won" || stage === "closed_lost";
  if (closed)
    return canReopen ? (
      <ActionDialog
        triggerLabel="Reopen"
        title="Reopen this deal?"
        description="The deal goes back into the open pipeline. Its close date (and lost reason) are cleared; the history keeps them."
        confirmLabel="Reopen deal"
        action={actions.reopen}
        initialState={initialDialogState}
      >
        {(errors) => (
          <DialogField
            id="reopen-stage"
            label="Back to stage"
            error={errors.stage}
          >
            {(p) => (
              <select name="stage" defaultValue="negotiation" {...p}>
                {OPEN_STAGES.map((s) => (
                  <option key={s} value={s}>
                    {STAGE_LABELS[s]}
                  </option>
                ))}
              </select>
            )}
          </DialogField>
        )}
      </ActionDialog>
    ) : null;
  if (!canEdit) return null;
  return (
    <div className="flex flex-wrap gap-2">
      <ButtonLink href={`/opportunities/${id}/edit`} variant="secondary">Edit</ButtonLink>
      <ActionDialog triggerLabel="Move stage" title="Move to another stage"
        description="Use this when the deal has progressed (or stepped back)." confirmLabel="Move"
        action={actions.move} initialState={initialDialogState}>
        {(errors) => (
          <>
            <DialogField id="move-stage" label="New stage" error={errors.stage}>
              {(p) => (
                <select name="stage" defaultValue="" {...p}>
                  <option value="" disabled>Choose…</option>
                  {OPEN_STAGES.filter((s) => s !== stage).map((s) => <option key={s} value={s}>{STAGE_LABELS[s]}</option>)}
                </select>
              )}
            </DialogField>
            <DialogField id="move-note" label="Note" optional error={errors.note}>
              {(p) => <input name="note" maxLength={500} {...p} />}
            </DialogField>
          </>
        )}
      </ActionDialog>
      <ActionDialog triggerLabel="Mark as won" triggerVariant="primary" title="Mark this deal as won?"
        description={hasAmount ? "Congratulations! The deal closes today as won." : "Add the deal value first (Edit): a won deal needs a value."}
        confirmLabel="Mark as won" action={actions.won} initialState={initialDialogState}>
        {(errors) => (
          <DialogField id="won-note" label="Note" optional error={errors.note}>
            {(p) => <input name="note" maxLength={500} placeholder="e.g. Contract signed" {...p} />}
          </DialogField>
        )}
      </ActionDialog>
      <ActionDialog triggerLabel="Mark as lost" triggerVariant="danger" title="Mark this deal as lost?"
        description="The deal closes today as lost. The reason helps the team learn." confirmLabel="Mark as lost"
        confirmVariant="danger" action={actions.lost} initialState={initialDialogState}>
        {(errors) => (
          <DialogField id="lost-reason" label="Reason" error={errors.reason}>
            {(p) => <textarea name="reason" rows={3} maxLength={500} placeholder="e.g. Chose a cheaper competitor" {...p} />}
          </DialogField>
        )}
      </ActionDialog>
    </div>
  ); // prettier-ignore
}
