"use client";

import { useId } from "react";

import { ActionDialog, DialogField } from "@/components/action-dialog";
import { PAYMENT_METHOD_LABELS, invoiceNumber } from "@/components/invoices";
import { formatMoney } from "@/components/orders";
import { PAYMENT_METHODS } from "@/lib/api-types";
import { type DialogState, initialDialogState } from "@/lib/dialog-state";

type Bound = (state: DialogState, formData: FormData) => Promise<DialogState>;

/** Invoice buttons. Every change asks for confirmation first; money changes are final. */
export function InvoiceActionBar({
  invoice,
  today,
  defaultDueDate,
  actions,
}: {
  invoice: {
    number: number | null;
    version: number;
    currency: string;
    balance: string;
  };
  today: string;
  defaultDueDate: string;
  actions: { issue?: Bound; discard?: Bound; pay?: Bound; credit?: Bound };
}) {
  if (!actions.issue && !actions.discard && !actions.pay && !actions.credit)
    return null;
  const label = invoiceNumber(invoice.number);
  const due = formatMoney(invoice.balance, invoice.currency);

  return (
    <div role="group" aria-label="Invoice actions" className="flex flex-wrap gap-2">
      {actions.issue && (
        <ActionDialog
          triggerLabel="Issue invoice"
          triggerVariant="primary"
          title="Issue this invoice?"
          description="It gets the next invoice number and can never be changed afterwards (corrections only with a credit note). The customer sees it in their portal."
          confirmLabel="Issue invoice"
          action={actions.issue}
          initialState={initialDialogState}
        >
          {(errors) => (
            <>
              <input type="hidden" name="version" value={invoice.version} />
              <DialogField id="invoice-due" label="Due date" error={errors.due_date} hint="Default: 14 days. At most 365 days.">
                {(props) => <input type="date" name="due_date" min={today} defaultValue={defaultDueDate} {...props} />}
              </DialogField>
            </>
          )}
        </ActionDialog>
      )}
      {actions.discard && (
        <ActionDialog
          triggerLabel="Discard draft"
          triggerVariant="danger"
          title="Discard this draft?"
          description="The draft never gets a number and the order can be invoiced again."
          confirmLabel="Discard draft"
          confirmVariant="danger"
          action={actions.discard}
          initialState={initialDialogState}
        >
          {() => <input type="hidden" name="version" value={invoice.version} />}
        </ActionDialog>
      )}
      {actions.pay && (
        <ActionDialog
          triggerLabel="Record payment"
          triggerVariant="primary"
          title={`Record a payment for ${label}`}
          description={<>Still owed: <strong>{due}</strong>. A payment cannot be edited later; a mistake is undone with a reversal.</>}
          confirmLabel="Record payment"
          action={actions.pay}
          initialState={initialDialogState}
        >
          {(errors) => (
            <>
              <DialogField id="payment-amount" label={`Amount (${invoice.currency})`} error={errors.amount}>
                {(props) => <input name="amount" inputMode="decimal" defaultValue={invoice.balance} {...props} />}
              </DialogField>
              <DialogField id="payment-date" label="Received on" error={errors.received_on}>
                {(props) => <input type="date" name="received_on" max={today} defaultValue={today} {...props} />}
              </DialogField>
              <DialogField id="payment-method" label="Method" error={errors.method}>
                {(props) => (
                  <select name="method" defaultValue="bank_transfer" {...props}>
                    {PAYMENT_METHODS.map((m) => <option key={m} value={m}>{PAYMENT_METHOD_LABELS[m]}</option>)}
                  </select>
                )}
              </DialogField>
              <DialogField id="payment-reference" label="Reference" optional hint="e.g. the bank statement reference" error={errors.reference}>
                {(props) => <input name="reference" maxLength={100} {...props} />}
              </DialogField>
            </>
          )}
        </ActionDialog>
      )}
      {actions.credit && (
        <ActionDialog
          triggerLabel="Issue credit note"
          title={`Issue a credit note for ${label}`}
          description={<>Reduces what the customer owes (at most {due}). The customer sees the credit note and its reason. It cannot be changed afterwards.</>}
          confirmLabel="Issue credit note"
          action={actions.credit}
          initialState={initialDialogState}
        >
          {(errors) => (
            <>
              <DialogField id="credit-reason" label="Reason (the customer will see this)" error={errors.reason}>
                {(props) => <input name="reason" maxLength={500} {...props} />}
              </DialogField>
              <DialogField id="credit-description" label="Description" error={errors.description}>
                {(props) => <input name="description" maxLength={500} defaultValue="Credit" {...props} />}
              </DialogField>
              <DialogField id="credit-amount" label={`Net amount (${invoice.currency})`} error={errors.unit_price}>
                {(props) => <input name="unit_price" inputMode="decimal" {...props} />}
              </DialogField>
              <DialogField id="credit-tax" label="Tax rate (%)" error={errors.tax_rate}>
                {(props) => <input name="tax_rate" inputMode="decimal" defaultValue="0" {...props} />}
              </DialogField>
            </>
          )}
        </ActionDialog>
      )}
    </div>
  ); // prettier-ignore
}

/** "Reverse" for one payment row. */
export function ReversePaymentButton({
  amount,
  action,
}: {
  amount: string;
  action: Bound;
}) {
  // One of these per payment row: the field id must be unique on the page.
  const id = useId();
  return (
    <ActionDialog
      triggerLabel="Reverse"
      title={`Reverse the payment of ${amount}?`}
      description="Use this for a payment entered by mistake or a transfer that bounced. Nothing is deleted: a reversal entry is added and the amount is owed again."
      confirmLabel="Reverse payment"
      confirmVariant="danger"
      action={action}
      initialState={initialDialogState}
    >
      {(errors) => (
        <DialogField
          id={`${id}-reason`}
          label="Reason"
          error={errors.reason}
          hint="Staff only."
        >
          {(props) => <input name="reason" maxLength={500} {...props} />}
        </DialogField>
      )}
    </ActionDialog>
  );
}
