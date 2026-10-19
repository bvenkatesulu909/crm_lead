"use client";

import { ActionDialog, DialogField } from "@/components/action-dialog";
import { PdfDownload } from "@/components/quote-view";
import { ButtonLink } from "@/components/ui";
import type { QuoteStatus } from "@/lib/api-types";
import type { DialogState } from "@/lib/dialog-state";
import { initialDialogState } from "@/lib/dialog-state";

type Action = (state: DialogState, formData: FormData) => Promise<DialogState>;

/**
 * Buttons for the quote's next steps. Which buttons appear is display only - the API checks
 * permissions, the four-eyes rule and the status flow again.
 */
export function QuoteActions({
  id,
  status,
  expired,
  needsApproval,
  hasOrder,
  hasPdf,
  recipient,
  can,
  act,
}: {
  id: string;
  status: QuoteStatus;
  expired: boolean;
  needsApproval: boolean;
  hasOrder: boolean;
  /** Sent at least once: a stored PDF exists or is made on download. */
  hasPdf: boolean;
  /** The quote's contact, if they have an e-mail address. */
  recipient: { name: string; email: string } | null;
  can: { write: boolean; approve: boolean; order: boolean };
  act: Record<
    | "submit"
    | "approve"
    | "reject"
    | "send"
    | "accept"
    | "decline"
    | "revise"
    | "order"
    | "email",
    Action
  >;
}) {
  const note = (id: string) =>
    function NoteField(errors: Record<string, string>) {
      return (
        <DialogField id={id} label="Note" optional error={errors.note}>
          {(p) => <input name="note" maxLength={500} {...p} />}
        </DialogField>
      );
    };
  const reason = (id: string, placeholder: string) =>
    function ReasonField(errors: Record<string, string>) {
      return (
        <DialogField id={id} label="Reason" error={errors.reason}>
          {(p) => (
            <textarea
              name="reason"
              rows={3}
              maxLength={500}
              placeholder={placeholder}
              {...p}
            />
          )}
        </DialogField>
      );
    };
  return (
    <div role="group" aria-label="Quote actions" className="flex flex-wrap gap-2">
      {status === "draft" && can.write && (
        <>
          <ButtonLink href={`/quotes/${id}/edit`} variant="secondary">Edit</ButtonLink>
          <ActionDialog triggerLabel="Submit" triggerVariant="primary" title="Submit this quote?"
            description={needsApproval ? "A discount is above the limit, so a manager must approve it before it can be sent." : "Prices are checked against the current price book; the quote is then ready to send."}
            confirmLabel="Submit" action={act.submit} initialState={initialDialogState}>
            {note("submit-note")}
          </ActionDialog>
        </>
      )}
      {status === "pending_approval" && can.approve && (
        <>
          <ActionDialog triggerLabel="Approve" triggerVariant="primary" title="Approve this quote?"
            description="You confirm the discounts. You can't approve your own quotes (four-eyes rule)."
            confirmLabel="Approve" action={act.approve} initialState={initialDialogState}>
            {note("approve-note")}
          </ActionDialog>
          <ActionDialog triggerLabel="Return to draft" title="Return this quote to draft?"
            description="The owner sees your reason and can change the quote." confirmLabel="Return"
            confirmVariant="danger" action={act.reject} initialState={initialDialogState}>
            {reason("reject-reason", "e.g. Max 20 % for this customer")}
          </ActionDialog>
        </>
      )}
      {status === "approved" && can.write && (
        <ActionDialog triggerLabel="Mark as sent" triggerVariant="primary" title="Mark as sent to the customer?"
          description="The customer can then see it in the portal and accept or decline it." confirmLabel="Mark as sent"
          action={act.send} initialState={initialDialogState}>
          {note("send-note")}
        </ActionDialog>
      )}
      {(status === "approved" || status === "sent") && can.write && (
        <ActionDialog
          triggerLabel={status === "sent" ? "E-mail again" : "Send by e-mail"}
          triggerVariant={status === "approved" ? "primary" : "secondary"}
          title={status === "sent" ? "E-mail this quote again?" : "Send this quote by e-mail?"}
          description={
            recipient
              ? `It goes to ${recipient.name} <${recipient.email}> with the PDF attached, and a link to the customer portal. Replies come to the quote's owner.`
              : "This quote has no contact with an e-mail address yet. Choose one on the quote (edit the draft or revise it), or use “Mark as sent” if you sent it another way."
          }
          confirmLabel={status === "sent" ? "E-mail again" : "Send e-mail"}
          action={act.email}
          initialState={initialDialogState}
        >
          {(errors) => (
            <DialogField id="email-message" label="Personal message" optional error={errors.message} hint="Shown at the top of the e-mail and kept in the history.">
              {(p) => <textarea name="message" rows={3} maxLength={500} {...p} />}
            </DialogField>
          )}
        </ActionDialog>
      )}
      {status === "sent" && can.write && (
        <>
          {!expired && (
            <ActionDialog triggerLabel="Record acceptance" triggerVariant="primary" title="The customer accepted?"
              description="Use this when the customer accepted outside the portal (e.g. signed PDF)." confirmLabel="Record acceptance"
              action={act.accept} initialState={initialDialogState}>
              {note("accept-note")}
            </ActionDialog>
          )}
          <ActionDialog triggerLabel="Record decline" title="The customer declined?" description="Record why, so the team can learn."
            confirmLabel="Record decline" confirmVariant="danger" action={act.decline} initialState={initialDialogState}>
            {reason("decline-reason", "e.g. Chose a cheaper offer")}
          </ActionDialog>
        </>
      )}
      {status === "accepted" && !hasOrder && can.order && (
        <ActionDialog triggerLabel="Create order" triggerVariant="primary" title="Create an order from this quote?"
          description="A draft order is created with the same lines and prices. You can review it before confirming."
          confirmLabel="Create order" action={act.order} initialState={initialDialogState}>
          {(errors) => (
            <DialogField id="order-reference" label="Customer reference" optional error={errors.customer_reference} hint="e.g. their purchase order number">
              {(p) => <input name="customer_reference" maxLength={100} {...p} />}
            </DialogField>
          )}
        </ActionDialog>
      )}
      {["pending_approval", "approved", "sent", "declined"].includes(status) && can.write && (
        <ActionDialog triggerLabel="Revise" title="Create a new revision?"
          description="A new draft with the same lines is made (prices refreshed from the price book). This version is kept as superseded."
          confirmLabel="Create revision" action={act.revise} initialState={initialDialogState} />
      )}
      {!["draft", "pending_approval", "superseded"].includes(status) && (
        <ButtonLink href={`/print/quotes/${id}`} variant="secondary">Print</ButtonLink>
      )}
      {hasPdf && (
        <PdfDownload href={`/quotes/${id}/pdf`} />
      )}
    </div>
  ); // prettier-ignore
}
