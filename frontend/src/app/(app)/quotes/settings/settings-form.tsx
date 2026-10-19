"use client";

import { useActionState } from "react";

import { DialogField } from "@/components/action-dialog";
import { ErrorAlert, buttonClass } from "@/components/ui";
import type { FormState } from "@/lib/form-state";
import { initialFormState } from "@/lib/form-state";

export function QuoteSettingsForm({
  action,
  current,
}: {
  action: (state: FormState, formData: FormData) => Promise<FormState>;
  current: string;
}) {
  const [state, formAction, pending] = useActionState(action, initialFormState);
  return (
    <form key={state.attempt} action={formAction} noValidate className="space-y-4">
      {state.error && <ErrorAlert title="The setting could not be saved" error={state.error} />}
      <div className="max-w-xs">
        <DialogField id="approval-limit" label="Approval needed above (%)" error={state.fieldErrors.approval_limit_percent}
          hint="0 = every discount needs approval; 100 = never.">
          {(p) => <input name="approval_limit_percent" inputMode="decimal" defaultValue={state.values.approval_limit_percent ?? current} {...p} />}
        </DialogField>
      </div>
      <button type="submit" disabled={pending} className={buttonClass("primary")}>{pending ? "Saving…" : "Save"}</button>
    </form>
  ); // prettier-ignore
}
