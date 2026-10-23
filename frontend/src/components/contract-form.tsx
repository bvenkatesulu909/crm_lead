"use client";

import Link from "next/link";
import { useActionState } from "react";

import { AccountPicker, type AccountOption } from "@/components/account-picker";
import { DialogField } from "@/components/action-dialog";
import { ErrorAlert, buttonClass } from "@/components/ui";
import { BILLING_FREQUENCIES, type Contract } from "@/lib/api-types";
import { BILLING_LABELS } from "@/lib/contracts";
import type { FormState } from "@/lib/form-state";

/**
 * Create or edit a contract. A draft shows every field; an ACTIVE contract shows only what may
 * still change (the account, dates and value change by renewing it). The API checks the same
 * rules again - what this form shows is display only.
 */
export function ContractForm({
  action,
  initialState,
  contract,
  defaultAccount,
  cancelHref,
  submitLabel,
}: {
  action: (state: FormState, formData: FormData) => Promise<FormState>;
  initialState: FormState;
  /** Present when editing. */
  contract?: Contract;
  /** The account to show as chosen when creating from an account page. */
  defaultAccount?: AccountOption | null;
  cancelHref: string;
  submitLabel: string;
}) {
  const [state, formAction, pending] = useActionState(action, initialState);
  const v = state.values;
  const e = state.fieldErrors;
  const active = contract?.status === "active";
  const count = Object.keys(e).length;
  const text = (name: string, fallback: string | null | undefined) =>
    v[name] ?? fallback ?? "";

  return (
    <form key={state.attempt} action={formAction} noValidate className="space-y-6">
      {state.error && <ErrorAlert title="The contract could not be saved" error={state.error} />}
      {count > 0 && (
        <div role="alert" className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          Please correct: {Object.values(e).join(" ")}
        </div>
      )}
      {active && (
        <p className="rounded-md bg-slate-50 p-3 text-sm text-slate-700">
          This contract is active, so its account, dates and value are fixed. To change them,
          renew the contract. You can still change the title, the renewal settings and the terms.
        </p>
      )}
      <div className="grid gap-5 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <DialogField id="contract-title" label="Title" error={e.title} hint="e.g. Annual support agreement">
            {(p) => <input name="title" maxLength={200} defaultValue={text("title", contract?.title)} {...p} />}
          </DialogField>
        </div>
        {contract ? (
          <div className="sm:col-span-2">
            <p className="text-sm font-medium text-slate-700">Account</p>
            <p className="mt-2 text-sm">{contract.account_name ?? "Account"}</p>
          </div>
        ) : (
          <div className="sm:col-span-2">
            <DialogField id="contract-account" label="Account" error={e.account_id}>
              {(p) => (
                <AccountPicker
                  {...p}
                  defaultAccount={
                    v.account_id && v.account_label
                      ? { id: v.account_id, name: v.account_label }
                      : defaultAccount
                  }
                />
              )}
            </DialogField>
          </div>
        )}
        {!active && (
          <>
            <DialogField id="contract-start" label="Start date" optional error={e.start_date} hint="Needed before the contract can be activated.">
              {(p) => <input type="date" name="start_date" defaultValue={text("start_date", contract?.start_date)} {...p} />}
            </DialogField>
            <DialogField id="contract-end" label="End date" optional error={e.end_date} hint="Needed before the contract can be activated.">
              {(p) => <input type="date" name="end_date" defaultValue={text("end_date", contract?.end_date)} {...p} />}
            </DialogField>
            <DialogField id="contract-value" label="Total value" error={e.total_value}>
              {(p) => <input name="total_value" inputMode="decimal" defaultValue={text("total_value", contract?.total_value ?? "0.00")} {...p} />}
            </DialogField>
            <DialogField id="contract-currency" label="Currency" error={e.currency}>
              {(p) => <input name="currency" maxLength={3} defaultValue={text("currency", contract?.currency ?? "EUR")} {...p} />}
            </DialogField>
            <DialogField id="contract-billing" label="Billed" error={e.billing_frequency}>
              {(p) => (
                <select name="billing_frequency" defaultValue={text("billing_frequency", contract?.billing_frequency ?? "annually")} {...p}>
                  {BILLING_FREQUENCIES.map((b) => <option key={b} value={b}>{BILLING_LABELS[b]}</option>)}
                </select>
              )}
            </DialogField>
          </>
        )}
        <DialogField id="contract-notice" label="Remind me before the end (days)" error={e.renewal_notice_days} hint="The owner is reminded once, this many days before the end date.">
          {(p) => <input name="renewal_notice_days" inputMode="numeric" defaultValue={text("renewal_notice_days", String(contract?.renewal_notice_days ?? 30))} {...p} />}
        </DialogField>
        <DialogField id="contract-term" label="Renewal term (months)" optional error={e.renewal_term_months} hint="How long a renewal lasts. Empty = as long as this contract.">
          {(p) => <input name="renewal_term_months" inputMode="numeric" defaultValue={text("renewal_term_months", contract?.renewal_term_months?.toString())} {...p} />}
        </DialogField>
        <div className="sm:col-span-2">
          <label className="flex items-start gap-3 text-sm text-slate-800">
            <input
              type="checkbox"
              name="auto_renew"
              defaultChecked={v.auto_renew !== undefined ? v.auto_renew === "on" : (contract?.auto_renew ?? false)}
              className="mt-0.5 size-4 rounded border-slate-300"
            />
            <span>
              <span className="font-medium">Prepare the renewal automatically</span>
              <span className="block text-slate-600">When the contract ends, a draft renewal is made for a manager to review and activate.</span>
            </span>
          </label>
        </div>
        <div className="sm:col-span-2">
          <DialogField id="contract-terms" label="Terms" optional error={e.terms} hint="Payment terms, scope, notice rules - whatever the team should be able to find quickly.">
            {(p) => <textarea name="terms" rows={6} maxLength={10000} defaultValue={text("terms", contract?.terms)} {...p} />}
          </DialogField>
        </div>
      </div>
      <div className="flex justify-end gap-3 border-t border-slate-200 pt-5">
        <Link href={cancelHref} className={buttonClass("secondary")}>Cancel</Link>
        <button type="submit" disabled={pending} className={buttonClass("primary")}>
          {pending ? "Saving…" : submitLabel}
        </button>
      </div>
    </form>
  ); // prettier-ignore
}
