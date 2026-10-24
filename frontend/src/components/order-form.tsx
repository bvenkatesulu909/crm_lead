"use client";

import Link from "next/link";
import { useActionState, useState } from "react";

import { DialogField } from "@/components/action-dialog";
import { AccountPicker, pickedAccount } from "@/components/account-picker";
import { formatMoney } from "@/components/orders";
import { ErrorAlert, buttonClass } from "@/components/ui";
import type { FormState } from "@/lib/form-state";
import { centsToDecimal, previewLine, sumLines } from "@/lib/order-math";
import { CURRENCIES, MAX_LINES } from "@/lib/validation/orders";

type Action = (state: FormState, formData: FormData) => Promise<FormState>;

export type LineRow = {
  product_code: string;
  description: string;
  quantity: string;
  unit_price: string;
  tax_rate: string;
};

export type OrderFormDefaults = {
  currency: string;
  customer_reference: string;
  expected_delivery_date: string;
  internal_note: string;
  lines: LineRow[];
};

const EMPTY_LINE: LineRow = {
  product_code: "",
  description: "",
  quantity: "1",
  unit_price: "",
  tax_rate: "0",
};

/** Restores the lines the user typed after a failed attempt (sent back as JSON). */
function initialLines(state: FormState, defaults: LineRow[]): LineRow[] {
  if (state.values.lines_json) {
    try {
      const parsed: unknown = JSON.parse(state.values.lines_json);
      if (Array.isArray(parsed)) return parsed as LineRow[];
    } catch {
      // fall through to the defaults
    }
  }
  return defaults.length > 0 ? defaults : [EMPTY_LINE];
}

/**
 * Create or edit a DRAFT order. The amounts shown while typing are a preview; the server
 * calculates and stores the real line amounts and totals.
 */
export function OrderForm({
  action,
  initialState,
  accounts,
  fixedAccountName,
  defaultAccountId,
  searchAccounts = false,
  defaultAccount,
  defaults,
  version,
  cancelHref,
  submitLabel,
}: {
  action: Action;
  initialState: FormState;
  /** Create: the accounts the user may order for. Edit: omit and pass fixedAccountName. */
  accounts?: { id: string; name: string }[];
  fixedAccountName?: string;
  defaultAccountId?: string;
  /** Create: search accounts by name as the user types instead of choosing from a fixed list. */
  searchAccounts?: boolean;
  /** With searchAccounts: the account to show as chosen when the form opens. */
  defaultAccount?: { id: string; name: string } | null;
  defaults: OrderFormDefaults;
  version?: number;
  cancelHref: string;
  submitLabel: string;
}) {
  const [state, formAction, pending] = useActionState(action, initialState);
  const errors = state.fieldErrors;
  const values = state.values;
  const [lines, setLines] = useState<LineRow[]>(() =>
    initialLines(state, defaults.lines),
  );
  const [currency, setCurrency] = useState(
    values.currency ?? defaults.currency,
  );
  const count = Object.keys(errors).length;

  const previews = lines.map((l) =>
    previewLine(l.quantity, l.unit_price, l.tax_rate),
  );
  const totals = sumLines(previews);
  const money = (cents: bigint) => formatMoney(centsToDecimal(cents), currency);
  const update = (index: number, field: keyof LineRow, value: string) =>
    setLines((rows) =>
      rows.map((row, i) => (i === index ? { ...row, [field]: value } : row)),
    );

  return (
    <form key={state.attempt} action={formAction} noValidate className="space-y-6">
      {state.error && <ErrorAlert title="The order could not be saved" error={state.error} />}
      {count > 0 && (
        <div role="alert" className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          Please correct {count === 1 ? "1 field" : `${count} fields`} below.
        </div>
      )}
      {version !== undefined && <input type="hidden" name="version" value={version} />}

      <div className="grid gap-5 sm:grid-cols-2">
        {accounts ? (
          <DialogField id="order-account" label="Customer account" error={errors.account_id}>
            {(props) => searchAccounts ? (
              <AccountPicker
                {...props}
                defaultAccount={pickedAccount(values, "account_id", "account_label", defaultAccount)}
              />
            ) : (
              <select name="account_id" defaultValue={values.account_id ?? defaultAccountId ?? (accounts.length === 1 ? accounts[0].id : "")} {...props}>
                <option value="" disabled>Choose an account…</option>
                {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            )}
          </DialogField>
        ) : (
          <div>
            <p className="text-sm font-medium text-slate-700">Customer account</p>
            <p className="mt-2 text-sm text-slate-900">{fixedAccountName}</p>
          </div>
        )}
        <DialogField id="order-currency" label="Currency" error={errors.currency}>
          {(props) => (
            <select name="currency" value={currency} onChange={(e) => setCurrency(e.target.value)} {...props}>
              {[...new Set([...CURRENCIES, currency])].map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          )}
        </DialogField>
        <DialogField id="order-reference" label="Customer reference" optional error={errors.customer_reference}
          hint="The customer's purchase-order number. They see it in the portal.">
          {(props) => <input name="customer_reference" maxLength={100} defaultValue={values.customer_reference ?? defaults.customer_reference} {...props} />}
        </DialogField>
        <DialogField id="order-delivery" label="Expected delivery" optional error={errors.expected_delivery_date}>
          {(props) => <input type="date" name="expected_delivery_date" defaultValue={values.expected_delivery_date ?? defaults.expected_delivery_date} {...props} />}
        </DialogField>
      </div>

      <fieldset>
        <legend className="text-base font-semibold text-slate-900">Order lines</legend>
        {errors.lines && <p role="alert" className="mt-1 text-sm text-red-700">{errors.lines}</p>}
        <ol className="mt-3 space-y-3">
          {lines.map((line, i) => {
            const n = i + 1;
            const e = (field: string) => errors[`lines.${i}.${field}`];
            const preview = previews[i];
            return (
              <li key={i}>
                <fieldset className="rounded-lg p-4 ring-1 ring-slate-200">
                  <legend className="px-1 text-sm font-medium text-slate-700">Line {n}</legend>
                  <div className="grid gap-3 sm:grid-cols-6">
                    <div className="sm:col-span-3">
                      <DialogField id={`line-${i}-description`} label="Description" error={e("description")}>
                        {(props) => <input name="line_description" maxLength={500} value={line.description} onChange={(ev) => update(i, "description", ev.target.value)} {...props} />}
                      </DialogField>
                    </div>
                    <div className="sm:col-span-3">
                      <DialogField id={`line-${i}-code`} label="Product code" optional error={e("product_code")}>
                        {(props) => <input name="line_product_code" maxLength={64} value={line.product_code} onChange={(ev) => update(i, "product_code", ev.target.value)} {...props} />}
                      </DialogField>
                    </div>
                    <div className="sm:col-span-2">
                      <DialogField id={`line-${i}-quantity`} label="Quantity" error={e("quantity")}>
                        {(props) => <input name="line_quantity" inputMode="decimal" value={line.quantity} onChange={(ev) => update(i, "quantity", ev.target.value)} {...props} />}
                      </DialogField>
                    </div>
                    <div className="sm:col-span-2">
                      <DialogField id={`line-${i}-price`} label={`Unit price (${currency})`} error={e("unit_price")}>
                        {(props) => <input name="line_unit_price" inputMode="decimal" placeholder="0.00" value={line.unit_price} onChange={(ev) => update(i, "unit_price", ev.target.value)} {...props} />}
                      </DialogField>
                    </div>
                    <div className="sm:col-span-2">
                      <DialogField id={`line-${i}-tax`} label="Tax rate (%)" error={e("tax_rate")}>
                        {(props) => <input name="line_tax_rate" inputMode="decimal" value={line.tax_rate} onChange={(ev) => update(i, "tax_rate", ev.target.value)} {...props} />}
                      </DialogField>
                    </div>
                  </div>
                  <div className="mt-3 flex items-center justify-between gap-3 text-sm">
                    <span className="text-slate-600" aria-live="polite">
                      {preview ? <>Line amount: <span className="font-medium tabular-nums text-slate-900">{money(preview.total)}</span></> : "Enter quantity and price to see the amount."}
                    </span>
                    {lines.length > 1 && (
                      <button type="button" aria-label={`Remove line ${n}`} className="font-medium text-red-700 hover:underline"
                        onClick={() => setLines((rows) => rows.filter((_, j) => j !== i))}>
                        Remove
                      </button>
                    )}
                  </div>
                </fieldset>
              </li>
            );
          })}
        </ol>
        {lines.length < MAX_LINES && (
          <button type="button" className={`${buttonClass("secondary")} mt-3`} onClick={() => setLines((rows) => [...rows, EMPTY_LINE])}>
            Add line
          </button>
        )}
        <dl aria-label="Order total preview" className="mt-4 ml-auto max-w-xs space-y-1 text-sm">
          <div className="flex justify-between gap-6"><dt className="text-slate-600">Subtotal</dt><dd className="tabular-nums">{money(totals.subtotal)}</dd></div>
          <div className="flex justify-between gap-6"><dt className="text-slate-600">Tax</dt><dd className="tabular-nums">{money(totals.tax)}</dd></div>
          <div className="flex justify-between gap-6 font-semibold text-slate-900"><dt>Total</dt><dd className="tabular-nums">{money(totals.total)}</dd></div>
          <p className="pt-1 text-xs text-slate-500">Preview. The final amounts are calculated when you save.</p>
        </dl>
      </fieldset>

      <DialogField id="order-note" label="Internal note" optional error={errors.internal_note}
        hint="For your colleagues only. Customers never see this note.">
        {(props) => <textarea name="internal_note" rows={3} maxLength={2000} defaultValue={values.internal_note ?? defaults.internal_note} {...props} />}
      </DialogField>

      <div className="flex justify-end gap-3 border-t border-slate-200 pt-5">
        <Link href={cancelHref} className={buttonClass("secondary")}>Cancel</Link>
        <button type="submit" disabled={pending} className={buttonClass("primary")}>
          {pending ? "Saving…" : submitLabel}
        </button>
      </div>
    </form>
  ); // prettier-ignore
}
