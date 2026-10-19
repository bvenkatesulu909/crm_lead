"use client";

import Link from "next/link";
import { useActionState } from "react";

import { DialogField } from "@/components/action-dialog";
import { ErrorAlert, buttonClass } from "@/components/ui";
import type { Product } from "@/lib/api-types";
import type { FormState } from "@/lib/form-state";
import { PRODUCT_TYPE_LABELS } from "@/lib/catalog";
import { PRODUCT_TYPES } from "@/lib/validation/catalog";

/** Create or edit a product. Prices are set per price book, not here. */
export function ProductForm({
  action,
  initialState,
  product,
  cancelHref,
  submitLabel,
}: {
  action: (state: FormState, formData: FormData) => Promise<FormState>;
  initialState: FormState;
  product?: Product;
  cancelHref: string;
  submitLabel: string;
}) {
  const [state, formAction, pending] = useActionState(action, initialState);
  const v = state.values;
  const e = state.fieldErrors;

  return (
    <form key={state.attempt} action={formAction} noValidate className="space-y-6">
      {state.error && <ErrorAlert title="The product could not be saved" error={state.error} />}
      <div className="grid gap-5 sm:grid-cols-2">
        <DialogField id="product-sku" label="Product code (SKU)" error={e.sku} hint="Unique, e.g. WID-100">
          {(p) => <input name="sku" maxLength={64} defaultValue={v.sku ?? product?.sku} {...p} />}
        </DialogField>
        <DialogField id="product-name" label="Name" error={e.name}>
          {(p) => <input name="name" maxLength={200} defaultValue={v.name ?? product?.name} {...p} />}
        </DialogField>
        <DialogField id="product-type" label="Type" error={e.product_type}>
          {(p) => (
            <select name="product_type" defaultValue={v.product_type ?? product?.product_type ?? "product"} {...p}>
              {PRODUCT_TYPES.map((t) => <option key={t} value={t}>{PRODUCT_TYPE_LABELS[t]}</option>)}
            </select>
          )}
        </DialogField>
        <DialogField id="product-unit" label="Unit" error={e.unit} hint="e.g. each, hour, month">
          {(p) => <input name="unit" maxLength={20} defaultValue={v.unit ?? product?.unit ?? "each"} {...p} />}
        </DialogField>
        <DialogField id="product-tax" label="Tax rate %" error={e.tax_rate} hint="e.g. 19 for 19 % VAT">
          {(p) => <input name="tax_rate" inputMode="decimal" defaultValue={v.tax_rate ?? (product ? String(Number(product.tax_rate)) : "0")} {...p} />}
        </DialogField>
        <div className="sm:col-span-2">
          <DialogField id="product-description" label="Description" optional error={e.description}>
            {(p) => <textarea name="description" rows={3} maxLength={5000} defaultValue={v.description ?? product?.description ?? ""} {...p} />}
          </DialogField>
        </div>
      </div>
      <div className="flex justify-end gap-3 border-t border-slate-200 pt-5">
        <Link href={cancelHref} className={buttonClass("secondary")}>Cancel</Link>
        <button type="submit" disabled={pending} className={buttonClass("primary")}>{pending ? "Saving…" : submitLabel}</button>
      </div>
    </form>
  ); // prettier-ignore
}
