"use client";

import { ActionDialog, DialogField } from "@/components/action-dialog";
import type { PriceBook } from "@/lib/api-types";
import type { DialogState } from "@/lib/dialog-state";
import { initialDialogState } from "@/lib/dialog-state";

/**
 * Dialogs for maintaining the catalogue (managers only - the API checks that again).
 * They live in a client file because the dialog bodies are render functions.
 */
type Action = (state: DialogState, formData: FormData) => Promise<DialogState>;

const check =
  "h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-600";

export function NewPriceBookDialog({ action }: { action: Action }) {
  return (
    <ActionDialog triggerLabel="New price book" triggerVariant="secondary" title="New price book"
      description="A price book holds the selling prices in one currency. Quotes take their prices from it."
      confirmLabel="Create" action={action} initialState={initialDialogState}>
      {(errors) => (
        <>
          <DialogField id="book-name" label="Name" error={errors.name} hint="e.g. Standard EUR, Partners USD">
            {(p) => <input name="name" maxLength={100} {...p} />}
          </DialogField>
          <DialogField id="book-currency" label="Currency" error={errors.currency} hint="3 letters, e.g. EUR">
            {(p) => <input name="currency" maxLength={3} defaultValue="EUR" {...p} />}
          </DialogField>
          <DialogField id="book-description" label="Description" optional error={errors.description}>
            {(p) => <input name="description" maxLength={500} {...p} />}
          </DialogField>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" name="is_default" className={check} /> Default book for this currency
          </label>
        </>
      )}
    </ActionDialog>
  ); // prettier-ignore
}

export function EditPriceBookDialog({
  action,
  book,
}: {
  action: Action;
  book: PriceBook;
}) {
  return (
    <ActionDialog triggerLabel="Edit price book" triggerVariant="secondary" title="Edit price book"
      description={`The currency (${book.currency}) can't be changed. Inactive books can't be used for new quotes.`}
      confirmLabel="Save" action={action} initialState={initialDialogState}>
      {(errors) => (
        <>
          <DialogField id="book-name" label="Name" error={errors.name}>
            {(p) => <input name="name" maxLength={100} defaultValue={book.name} {...p} />}
          </DialogField>
          <DialogField id="book-description" label="Description" optional error={errors.description}>
            {(p) => <input name="description" maxLength={500} defaultValue={book.description ?? ""} {...p} />}
          </DialogField>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" name="is_default" defaultChecked={book.is_default} className={check} /> Default book for {book.currency}
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" name="is_active" defaultChecked={book.is_active} className={check} /> Active
          </label>
        </>
      )}
    </ActionDialog>
  ); // prettier-ignore
}

/** Add a price (choose a product) or change one (`product` given). */
export function SetPriceDialog({
  action,
  currency,
  products,
  product,
}: {
  action: Action;
  currency: string;
  products?: { id: string; label: string }[];
  product?: { name: string; price: string };
}) {
  return (
    <ActionDialog
      triggerLabel={product ? "Change price" : "Add price"}
      triggerVariant={product ? "secondary" : "primary"}
      title={product ? `Price of ${product.name}` : "Add a product to this price book"}
      description="The new price applies to quotes created or revised from now on. Sent quotes keep their prices."
      confirmLabel="Save price" action={action} initialState={initialDialogState}>
      {(errors) => (
        <>
          {products && (
            <DialogField id="price-product" label="Product" error={errors.product_id}>
              {(p) => (
                <select name="product_id" defaultValue="" {...p}>
                  <option value="">Choose a product…</option>
                  {products.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}
                </select>
              )}
            </DialogField>
          )}
          <DialogField id="price-amount" label={`Unit price (${currency}, without tax)`} error={errors.unit_price}>
            {(p) => <input name="unit_price" inputMode="decimal" defaultValue={product ? product.price : ""} {...p} />}
          </DialogField>
        </>
      )}
    </ActionDialog>
  ); // prettier-ignore
}

export function RemovePriceDialog({
  action,
  name,
}: {
  action: Action;
  name: string;
}) {
  return (
    <ActionDialog triggerLabel="Remove" triggerVariant="secondary" title={`Remove ${name} from this price book?`}
      description="It can no longer be added to quotes that use this book. Existing quotes are not changed."
      confirmLabel="Remove" confirmVariant="danger" action={action} initialState={initialDialogState} />
  ); // prettier-ignore
}

export function ProductActiveDialog({
  action,
  active,
}: {
  action: Action;
  active: boolean;
}) {
  return active ? (
    <ActionDialog triggerLabel="Deactivate" triggerVariant="secondary" title="Deactivate this product?"
      description="It can no longer be added to quotes. Existing quotes and orders keep it." confirmLabel="Deactivate"
      confirmVariant="danger" action={action} initialState={initialDialogState} />
  ) : (
    <ActionDialog triggerLabel="Activate" triggerVariant="secondary" title="Activate this product?"
      description="It can be added to quotes again (if it has a price in the price book)." confirmLabel="Activate"
      action={action} initialState={initialDialogState} />
  ); // prettier-ignore
}
