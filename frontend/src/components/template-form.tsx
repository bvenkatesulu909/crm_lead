"use client";

import Link from "next/link";
import { useActionState } from "react";

import { DialogField } from "@/components/action-dialog";
import { ErrorAlert, buttonClass } from "@/components/ui";
import type { EmailTemplate, Placeholder } from "@/lib/api-types";
import type { FormState } from "@/lib/form-state";

/**
 * Create or edit an e-mail template. Placeholders come from a fixed list (shown beside the
 * form); anything else is refused here and again by the API.
 */
export function TemplateForm({
  action,
  initialState,
  template,
  placeholders,
  submitLabel,
}: {
  action: (state: FormState, formData: FormData) => Promise<FormState>;
  initialState: FormState;
  /** Present when editing. */
  template?: EmailTemplate;
  placeholders: Placeholder[];
  submitLabel: string;
}) {
  const [state, formAction, pending] = useActionState(action, initialState);
  const v = state.values;
  const e = state.fieldErrors;
  const text = (name: "name" | "subject" | "body") => v[name] ?? template?.[name] ?? "";

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <form key={state.attempt} action={formAction} noValidate className="space-y-5 lg:col-span-2">
        {state.error && <ErrorAlert title="The template could not be saved" error={state.error} />}
        <DialogField id="template-name" label="Name" error={e.name} hint="Only you and your colleagues see it, e.g. First reply">
          {(p) => <input name="name" maxLength={120} defaultValue={text("name")} {...p} />}
        </DialogField>
        <DialogField id="template-subject" label="Subject" error={e.subject}>
          {(p) => <input name="subject" maxLength={200} defaultValue={text("subject")} {...p} />}
        </DialogField>
        <DialogField id="template-body" label="Text" error={e.body} hint="Plain text. Line breaks are kept.">
          {(p) => <textarea name="body" rows={12} maxLength={20000} defaultValue={text("body")} {...p} />}
        </DialogField>
        <div className="flex gap-3">
          <button type="submit" disabled={pending} className={buttonClass("primary")}>
            {pending ? "Saving…" : submitLabel}
          </button>
          <Link href="/communications/templates" className={buttonClass("secondary")}>Cancel</Link>
        </div>
      </form>
      <aside aria-labelledby="placeholder-heading" className="rounded-lg bg-slate-50 p-5 text-sm">
        <h2 id="placeholder-heading" className="font-semibold text-slate-900">Placeholders</h2>
        <p className="mt-1 text-slate-600">
          Type one of these in the subject or text. When an e-mail is written, it is replaced by
          the value; an empty value is left out.
        </p>
        <dl className="mt-3 space-y-2">
          {placeholders.map((p) => (
            <div key={p.name}>
              <dt className="font-mono text-xs text-slate-900">{`{{${p.name}}}`}</dt>
              <dd className="text-xs text-slate-600">{p.description}</dd>
            </div>
          ))}
        </dl>
      </aside>
    </div>
  ); // prettier-ignore
}
