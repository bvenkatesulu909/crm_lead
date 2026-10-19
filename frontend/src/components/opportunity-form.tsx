"use client";

import Link from "next/link";
import { useActionState, useState } from "react";

import { DialogField } from "@/components/action-dialog";
import { ErrorAlert, buttonClass } from "@/components/ui";
import { OPEN_STAGES, type Opportunity } from "@/lib/api-types";
import type { FormState } from "@/lib/form-state";
import { STAGE_LABELS } from "@/lib/pipeline";

type Option = { id: string; name: string };
type ContactOption = Option & { accountId: string | null };

/**
 * Create or edit an opportunity. The contact list follows the chosen account: a deal's
 * primary contact must work at the deal's account (the API checks this too).
 */
export function OpportunityForm({
  action,
  initialState,
  opportunity,
  defaultAccountId,
  accounts,
  contacts,
  owners,
  cancelHref,
  submitLabel,
}: {
  action: (state: FormState, formData: FormData) => Promise<FormState>;
  initialState: FormState;
  opportunity?: Opportunity;
  defaultAccountId?: string;
  accounts: Option[];
  contacts: ContactOption[];
  owners?: Option[];
  cancelHref: string;
  submitLabel: string;
}) {
  const [state, formAction, pending] = useActionState(action, initialState);
  const e = state.fieldErrors;
  const v = (field: keyof Opportunity & string, fallback = ""): string => {
    if (state.values[field] !== undefined) return state.values[field];
    const saved = opportunity?.[field];
    return saved === null || saved === undefined ? fallback : String(saved);
  };
  const [accountId, setAccountId] = useState(
    v("account_id", defaultAccountId ?? ""),
  );
  const people = contacts.filter((c) => c.accountId === accountId);
  const count = Object.keys(e).length;

  return (
    <form key={state.attempt} action={formAction} noValidate className="space-y-5">
      {state.error && <ErrorAlert title="The opportunity could not be saved" error={state.error} />}
      {count > 0 && (
        <div role="alert" className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          Please correct {count === 1 ? "1 field" : `${count} fields`} below.
        </div>
      )}
      <div className="grid gap-5 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <DialogField id="opp-name" label="Name" error={e.name} hint="What is being sold, e.g. 50 licences – annual plan.">
            {(p) => <input name="name" maxLength={255} defaultValue={v("name")} {...p} />}
          </DialogField>
        </div>
        {opportunity ? (
          <div>
            <p className="text-sm font-medium text-slate-700">Account</p>
            <p className="mt-2 text-sm text-slate-900">{accounts.find((a) => a.id === accountId)?.name ?? "Account"}</p>
            <input type="hidden" name="account_id" value={accountId} />
          </div>
        ) : (
          <DialogField id="opp-account" label="Account" error={e.account_id}>
            {(p) => (
              <select name="account_id" value={accountId} onChange={(ev) => setAccountId(ev.target.value)} {...p}>
                <option value="">Choose an account…</option>
                {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            )}
          </DialogField>
        )}
        <DialogField id="opp-contact" label="Primary contact" optional error={e.primary_contact_id}
          hint={accountId ? undefined : "Choose the account first."}>
          {(p) => (
            <select name="primary_contact_id" key={accountId} defaultValue={v("primary_contact_id")} disabled={!accountId} {...p}>
              <option value="">None</option>
              {people.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          )}
        </DialogField>
        {!opportunity && (
          <DialogField id="opp-stage" label="Stage" error={e.stage}>
            {(p) => (
              <select name="stage" defaultValue={v("stage", "prospecting")} {...p}>
                {OPEN_STAGES.map((s) => <option key={s} value={s}>{STAGE_LABELS[s]}</option>)}
              </select>
            )}
          </DialogField>
        )}
        <div className="grid grid-cols-[1fr_6rem] gap-3">
          <DialogField id="opp-amount" label="Estimated value" optional error={e.amount}>
            {(p) => <input name="amount" inputMode="decimal" placeholder="0.00" defaultValue={v("amount")} {...p} />}
          </DialogField>
          <DialogField id="opp-currency" label="Currency" error={e.currency}>
            {(p) => <input name="currency" maxLength={3} defaultValue={v("currency", "EUR")} {...p} />}
          </DialogField>
        </div>
        <DialogField id="opp-close" label="Expected close date" optional error={e.expected_close_date}>
          {(p) => <input name="expected_close_date" type="date" defaultValue={v("expected_close_date")} {...p} />}
        </DialogField>
        {owners && (
          <DialogField id="opp-owner" label="Deal owner" optional error={e.owner_id}>
            {(p) => (
              <select name="owner_id" defaultValue={v("owner_id")} {...p}>
                <option value="">{opportunity ? "Nobody" : "Default (you, if you work in sales)"}</option>
                {owners.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
              </select>
            )}
          </DialogField>
        )}
        <div className="sm:col-span-2">
          <DialogField id="opp-next" label="Next step" optional error={e.next_step} hint="The next concrete action, e.g. Send proposal by Friday.">
            {(p) => <input name="next_step" maxLength={500} defaultValue={v("next_step")} {...p} />}
          </DialogField>
        </div>
        <div className="sm:col-span-2">
          <DialogField id="opp-description" label="Description" optional error={e.description}>
            {(p) => <textarea name="description" rows={4} maxLength={5000} defaultValue={v("description")} {...p} />}
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
