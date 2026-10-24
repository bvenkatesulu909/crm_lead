"use client";

import Link from "next/link";
import { useActionState } from "react";

import { DialogField } from "@/components/action-dialog";
import { AccountPicker, pickedAccount } from "@/components/account-picker";
import { DuplicateNotice } from "@/components/duplicate-notice";
import { ErrorAlert, buttonClass } from "@/components/ui";
import {
  ACCOUNT_TYPES,
  CHANNELS,
  EMAIL_CONSENTS,
  LIFECYCLE_STAGES,
  SEGMENTS,
  type Account,
  type Contact,
} from "@/lib/api-types";
import {
  ACCOUNT_TYPE_LABELS,
  CHANNEL_LABELS,
  CONSENT_LABELS,
  COUNTRIES,
  LANGUAGES,
  LIFECYCLE_LABELS,
  SEGMENT_LABELS,
} from "@/lib/customer-data";
import type { FormState } from "@/lib/form-state";

type Action = (state: FormState, formData: FormData) => Promise<FormState>;
type Option = { id: string; name: string };

function FormErrors({ state, what }: { state: FormState; what: string }) {
  const count = Object.keys(state.fieldErrors).length;
  return (
    <>
      {state.error && (
        <ErrorAlert
          title={`The ${what} could not be saved`}
          error={state.error}
        />
      )}
      {count > 0 && (
        <div
          role="alert"
          className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
        >
          Please correct {count === 1 ? "1 field" : `${count} fields`} below.
        </div>
      )}
    </>
  );
}

function Buttons({
  cancelHref,
  pending,
  label,
}: {
  cancelHref: string;
  pending: boolean;
  label: string;
}) {
  return (
    <div className="flex justify-end gap-3 border-t border-slate-200 pt-5">
      <Link href={cancelHref} className={buttonClass("secondary")}>
        Cancel
      </Link>
      <button
        type="submit"
        disabled={pending}
        className={buttonClass("primary")}
      >
        {pending ? "Saving…" : label}
      </button>
    </div>
  );
}

/** Create or edit an account. `owners` is given only to users who may choose the owner. */
export function AccountForm({
  action,
  initialState,
  account,
  defaultParent,
  owners,
  cancelHref,
  submitLabel,
}: {
  action: Action;
  initialState: FormState;
  account?: Account;
  /** The parent to show as chosen when the form opens (create: from ?parent=, edit: the saved one). */
  defaultParent?: Option | null;
  owners?: Option[];
  cancelHref: string;
  submitLabel: string;
}) {
  const [state, formAction, pending] = useActionState(action, initialState);
  const e = state.fieldErrors;
  // After a failed attempt show what the user typed; otherwise the saved values.
  const v = (field: keyof Account & string): string => {
    if (state.values[field] !== undefined) return state.values[field];
    const saved = account?.[field];
    return saved === null || saved === undefined ? "" : String(saved);
  };

  return (
    <form key={state.attempt} action={formAction} noValidate className="space-y-5">
      <FormErrors state={state} what="account" />
      {state.duplicates && <DuplicateNotice notice={state.duplicates} what="customer" />}
      <div className="grid gap-5 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <DialogField id="account-name" label="Name" error={e.name}>
            {(p) => <input name="name" maxLength={255} defaultValue={v("name")} {...p} />}
          </DialogField>
        </div>
        <DialogField id="account-number" label="Account number" optional error={e.account_number}
          hint="Your own or ERP number; must be unique.">
          {(p) => <input name="account_number" maxLength={50} defaultValue={v("account_number")} {...p} />}
        </DialogField>
        <DialogField id="account-industry" label="Industry" optional error={e.industry}>
          {(p) => <input name="industry" maxLength={100} defaultValue={v("industry")} {...p} />}
        </DialogField>
        <DialogField id="account-segment" label="Segment" optional error={e.segment}>
          {(p) => (
            <select name="segment" defaultValue={v("segment")} {...p}>
              <option value="">Not set</option>
              {SEGMENTS.map((s) => <option key={s} value={s}>{SEGMENT_LABELS[s]}</option>)}
            </select>
          )}
        </DialogField>
        <DialogField id="account-channel" label="Preferred contact channel" optional error={e.preferred_channel}>
          {(p) => (
            <select name="preferred_channel" defaultValue={v("preferred_channel")} {...p}>
              <option value="">Not set</option>
              {CHANNELS.map((c) => <option key={c} value={c}>{CHANNEL_LABELS[c]}</option>)}
            </select>
          )}
        </DialogField>
        <DialogField id="account-lifecycle" label="Lifecycle stage" optional error={e.lifecycle_stage}>
          {(p) => (
            <select name="lifecycle_stage" defaultValue={v("lifecycle_stage")} {...p}>
              <option value="">Not set</option>
              {LIFECYCLE_STAGES.map((s) => <option key={s} value={s}>{LIFECYCLE_LABELS[s]}</option>)}
            </select>
          )}
        </DialogField>
        <DialogField id="account-type" label="Account type" error={e.account_type}
          hint="Head office, subsidiary or branch of a group (set the parent below).">
          {(p) => (
            <select name="account_type" defaultValue={v("account_type") || "company"} {...p}>
              {ACCOUNT_TYPES.map((t) => <option key={t} value={t}>{ACCOUNT_TYPE_LABELS[t]}</option>)}
            </select>
          )}
        </DialogField>
        <DialogField id="account-country" label="Country" optional error={e.country} hint="2-letter code, e.g. IN.">
          {(p) => (
            <>
              <input name="country" list="country-codes" maxLength={2} defaultValue={v("country")} {...p} />
              <datalist id="country-codes">
                {COUNTRIES.map(([c, n]) => <option key={c} value={c}>{n}</option>)}
              </datalist>
            </>
          )}
        </DialogField>
        <DialogField id="account-region" label="Region / state" optional error={e.region}>
          {(p) => <input name="region" maxLength={100} defaultValue={v("region")} {...p} />}
        </DialogField>
        <DialogField id="account-city" label="City" optional error={e.city}>
          {(p) => <input name="city" maxLength={100} defaultValue={v("city")} {...p} />}
        </DialogField>
        <DialogField id="account-language" label="Preferred language" optional error={e.preferred_language}>
          {(p) => (
            <select name="preferred_language" defaultValue={v("preferred_language")} {...p}>
              <option value="">Not set</option>
              {LANGUAGES.map(([c, n]) => <option key={c} value={c}>{n}</option>)}
            </select>
          )}
        </DialogField>
        <DialogField id="account-phone" label="Phone" optional error={e.phone}>
          {(p) => <input name="phone" type="tel" maxLength={50} defaultValue={v("phone")} {...p} />}
        </DialogField>
        <DialogField id="account-website" label="Website" optional error={e.website}>
          {(p) => <input name="website" type="url" maxLength={2048} placeholder="https://" defaultValue={v("website")} {...p} />}
        </DialogField>
        <DialogField id="account-parent" label="Parent account" optional error={e.parent_account_id}
          hint="The group or head office this account belongs to.">
          {(p) => (
            <AccountPicker
              {...p}
              name="parent_account_id"
              labelName="parent_account_label"
              placeholder="None - type to search for a parent account"
              excludeId={account?.id}
              defaultAccount={pickedAccount(state.values, "parent_account_id", "parent_account_label", defaultParent)}
            />
          )}
        </DialogField>
        {owners && (
          <DialogField id="account-owner" label="Owner" optional error={e.owner_id}
            hint="The sales rep responsible for this customer.">
            {(p) => (
              <select name="owner_id" defaultValue={v("owner_id")} {...p}>
                <option value="">{account ? "Nobody" : "Default (you, if you work in sales)"}</option>
                {owners.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
              </select>
            )}
          </DialogField>
        )}
      </div>
      <Buttons cancelHref={cancelHref} pending={pending} label={submitLabel} />
    </form>
  ); // prettier-ignore
}

/** Create or edit a contact. */
export function ContactForm({
  action,
  initialState,
  contact,
  defaultAccount,
  owners,
  cancelHref,
  submitLabel,
}: {
  action: Action;
  initialState: FormState;
  contact?: Contact;
  /** The account to show as chosen when the form opens (create: from ?account=, edit: the saved one). */
  defaultAccount?: Option | null;
  owners?: Option[];
  cancelHref: string;
  submitLabel: string;
}) {
  const [state, formAction, pending] = useActionState(action, initialState);
  const e = state.fieldErrors;
  const v = (field: keyof Contact & string): string => {
    if (state.values[field] !== undefined) return state.values[field];
    const saved = contact?.[field];
    return saved === null || saved === undefined ? "" : String(saved);
  };
  const checked = (field: "is_primary" | "do_not_call") =>
    state.attempt > 0
      ? state.values[field] === "on"
      : Boolean(contact?.[field]);

  return (
    <form key={state.attempt} action={formAction} noValidate className="space-y-6">
      <FormErrors state={state} what="contact" />
      {state.duplicates && <DuplicateNotice notice={state.duplicates} what="contact" />}
      <fieldset className="grid gap-5 sm:grid-cols-2">
        <legend className="mb-3 text-sm font-semibold text-slate-900">Person</legend>
        <DialogField id="contact-first" label="First name" optional error={e.first_name}>
          {(p) => <input name="first_name" maxLength={100} defaultValue={v("first_name")} {...p} />}
        </DialogField>
        <DialogField id="contact-last" label="Last name" error={e.last_name}>
          {(p) => <input name="last_name" maxLength={100} defaultValue={v("last_name")} {...p} />}
        </DialogField>
        <DialogField id="contact-title" label="Designation" optional error={e.job_title} hint="Job title, e.g. Head of IT.">
          {(p) => <input name="job_title" maxLength={150} defaultValue={v("job_title")} {...p} />}
        </DialogField>
        <DialogField id="contact-department" label="Department" optional error={e.department}>
          {(p) => <input name="department" maxLength={100} defaultValue={v("department")} {...p} />}
        </DialogField>
      </fieldset>

      <fieldset className="grid gap-5 sm:grid-cols-2">
        <legend className="mb-3 text-sm font-semibold text-slate-900">Account</legend>
        <DialogField id="contact-account" label="Account" optional error={e.account_id}>
          {(p) => (
            <AccountPicker
              {...p}
              placeholder="No account - type to search"
              defaultAccount={pickedAccount(state.values, "account_id", "account_label", defaultAccount)}
            />
          )}
        </DialogField>
        {owners && (
          <DialogField id="contact-owner" label="Owner" optional error={e.owner_id}>
            {(p) => (
              <select name="owner_id" defaultValue={v("owner_id")} {...p}>
                <option value="">{contact ? "Nobody" : "Default (you, if you work in sales)"}</option>
                {owners.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
              </select>
            )}
          </DialogField>
        )}
        <div className="sm:col-span-2">
          <input type="hidden" name="is_primary__present" value="1" />
          <label className="flex items-start gap-2 text-sm text-slate-700">
            <input type="checkbox" name="is_primary" defaultChecked={checked("is_primary")}
              aria-describedby="contact-primary-hint" className="mt-0.5" />
            <span>
              Primary contact of the account
              <span id="contact-primary-hint" className="block text-xs text-slate-500">
                The main person to talk to. Replaces the account&apos;s current primary contact.
              </span>
            </span>
          </label>
          {e.is_primary && <p className="mt-1 text-sm text-red-700">{e.is_primary}</p>}
        </div>
      </fieldset>

      <fieldset className="grid gap-5 sm:grid-cols-3">
        <legend className="mb-3 text-sm font-semibold text-slate-900">Communication</legend>
        <DialogField id="contact-email" label="E-mail" optional error={e.email}>
          {(p) => <input name="email" type="email" maxLength={320} defaultValue={v("email")} {...p} />}
        </DialogField>
        <DialogField id="contact-phone" label="Phone" optional error={e.phone}>
          {(p) => <input name="phone" type="tel" maxLength={50} defaultValue={v("phone")} {...p} />}
        </DialogField>
        <DialogField id="contact-mobile" label="Mobile" optional error={e.mobile}>
          {(p) => <input name="mobile" type="tel" maxLength={50} defaultValue={v("mobile")} {...p} />}
        </DialogField>
      </fieldset>

      <fieldset className="grid gap-5 sm:grid-cols-2">
        <legend className="mb-3 text-sm font-semibold text-slate-900">Preferences and consent</legend>
        <DialogField id="contact-channel" label="Preferred channel" optional error={e.preferred_channel}>
          {(p) => (
            <select name="preferred_channel" defaultValue={v("preferred_channel")} {...p}>
              <option value="">Not set</option>
              {CHANNELS.map((c) => <option key={c} value={c}>{CHANNEL_LABELS[c]}</option>)}
            </select>
          )}
        </DialogField>
        <DialogField id="contact-consent" label="Marketing e-mail consent" error={e.email_consent}
          hint="Record only what the person told you. The date is saved automatically.">
          {(p) => (
            <select name="email_consent" defaultValue={v("email_consent") || "unknown"} {...p}>
              {EMAIL_CONSENTS.map((c) => <option key={c} value={c}>{CONSENT_LABELS[c]}</option>)}
            </select>
          )}
        </DialogField>
        <DialogField id="contact-language" label="Preferred language" optional error={e.preferred_language}>
          {(p) => (
            <select name="preferred_language" defaultValue={v("preferred_language")} {...p}>
              <option value="">Not set</option>
              {LANGUAGES.map(([c, n]) => <option key={c} value={c}>{n}</option>)}
            </select>
          )}
        </DialogField>
        <div className="sm:col-span-2">
          <input type="hidden" name="do_not_call__present" value="1" />
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" name="do_not_call" defaultChecked={checked("do_not_call")} />
            Do not call this person
          </label>
        </div>
      </fieldset>
      <Buttons cancelHref={cancelHref} pending={pending} label={submitLabel} />
    </form>
  ); // prettier-ignore
}
