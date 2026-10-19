"use client";

import { useActionState } from "react";

import { DialogField } from "@/components/action-dialog";
import { ErrorAlert, buttonClass } from "@/components/ui";
import type { FormState } from "@/lib/form-state";

type Action = (state: FormState, formData: FormData) => Promise<FormState>;

/** "Enter your organisation's sign-up code" - sends an access request, nothing more. */
export function SignupCodeForm({
  action,
  initialState,
}: {
  action: Action;
  initialState: FormState;
}) {
  const [state, formAction, pending] = useActionState(action, initialState);
  return (
    <form key={state.attempt} action={formAction} noValidate className="space-y-4">
      {state.error && <ErrorAlert title="Your request could not be sent" error={state.error} />}
      <DialogField id="signup-code" label="Organisation sign-up code" error={state.fieldErrors.signup_code}
        hint="Ask your company's CRM administrator for it. It looks like ABCD-EFGH-JKMN.">
        {(props) => (
          <input name="signup_code" autoComplete="off" spellCheck={false} maxLength={20}
            placeholder="XXXX-XXXX-XXXX" defaultValue={state.values.signup_code}
            {...props} className={`${props.className} font-mono uppercase`} />
        )}
      </DialogField>
      <button type="submit" disabled={pending} className={`${buttonClass("primary")} w-full`}>
        {pending ? "Sending…" : "Request access"}
      </button>
    </form>
  ); // prettier-ignore
}
