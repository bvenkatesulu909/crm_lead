"use client";

import { ActionDialog, DialogField } from "@/components/action-dialog";
import { orderNumber } from "@/components/orders";
import { ButtonLink } from "@/components/ui";
import { type DialogState, initialDialogState } from "@/lib/dialog-state";
import { ORDER_ACTIONS, type OrderTarget } from "@/lib/order-rules";

type Bound = (state: DialogState, formData: FormData) => Promise<DialogState>;

/** Order buttons. Every status change asks for confirmation first. */
export function OrderActionBar({
  order,
  editHref,
  actions,
  invoiced = false,
}: {
  order: { number: number; version: number; expectedDelivery: string | null };
  /** Shown for drafts the user may edit. */
  editHref?: string;
  actions: Partial<Record<OrderTarget, Bound>>;
  /** Warn before cancelling: the invoice must then be corrected with a credit note. */
  invoiced?: boolean;
}) {
  const targets = Object.keys(actions) as OrderTarget[];
  if (!editHref && targets.length === 0) return null;
  const label = orderNumber(order.number);

  return (
    <div role="group" aria-label="Order actions" className="flex flex-wrap gap-2">
      {editHref && <ButtonLink href={editHref} variant="secondary">Edit draft</ButtonLink>}
      {targets.map((target) => {
        const info = ORDER_ACTIONS[target];
        const action = actions[target];
        if (!action) return null;
        return (
          <ActionDialog
            key={target}
            triggerLabel={info.label}
            triggerVariant={info.danger ? "danger" : info.primary ? "primary" : "secondary"}
            title={`${info.label} ${label}?`}
            description={
              target === "cancelled" && invoiced ? (
                <>
                  {info.confirm}{" "}
                  <strong>This order is already invoiced:</strong> issue a credit note for the invoice too.
                </>
              ) : (
                info.confirm
              )
            }
            confirmLabel={info.label}
            confirmVariant={info.danger ? "danger" : "primary"}
            action={action}
            initialState={initialDialogState}
          >
            {(errors) => (
              <>
                <input type="hidden" name="version" value={order.version} />
                {target === "cancelled" && (
                  <DialogField id="order-cancel-reason" label="Reason (the customer will see this)" error={errors.reason}>
                    {(props) => <input name="reason" maxLength={500} required {...props} />}
                  </DialogField>
                )}
                {target === "shipped" && (
                  <DialogField id="order-tracking" label="Tracking reference" optional error={errors.tracking_reference}>
                    {(props) => <input name="tracking_reference" maxLength={200} {...props} />}
                  </DialogField>
                )}
                {["confirmed", "in_fulfilment", "shipped"].includes(target) && (
                  <DialogField id={`order-delivery-${target}`} label="Expected delivery" optional error={errors.expected_delivery_date}>
                    {(props) => <input type="date" name="expected_delivery_date" defaultValue={order.expectedDelivery ?? ""} {...props} />}
                  </DialogField>
                )}
                <DialogField id={`order-note-${target}`} label="Internal note" optional hint="Staff only, saved in the history." error={errors.note}>
                  {(props) => <input name="note" maxLength={2000} {...props} />}
                </DialogField>
              </>
            )}
          </ActionDialog>
        );
      })}
    </div>
  ); // prettier-ignore
}
