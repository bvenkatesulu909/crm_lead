"use client";

import { useActionState, useId, useState } from "react";

import { DialogField } from "@/components/action-dialog";
import { ErrorAlert, buttonClass } from "@/components/ui";
import type { WebCheckSource } from "@/lib/api-types";
import { initialDialogState, type DialogState } from "@/lib/dialog-state";
import { requestErrorText } from "@/lib/webcheck";

type Action = (state: DialogState, formData: FormData) => Promise<DialogState>;

const QUERY_LABELS: Record<WebCheckSource["kind"], string> = {
  rera: "RERA number",
  company: "Company name",
};

/**
 * Ask for a web check: where to look, and the number or name to look up. Only those two fields
 * are sent - never who is asking or which organisation (the server knows). What was typed stays
 * when the server reports a problem. The result is fetched in the background: it appears on the
 * page and the person gets a notification.
 */
export function WebCheckForm({
  sources,
  action,
}: {
  sources: WebCheckSource[];
  action: Action;
}) {
  const [state, formAction, pending] = useActionState(
    action,
    initialDialogState,
  );
  const id = useId();
  const [sourceKey, setSourceKey] = useState(sources[0]?.key ?? "");
  const [query, setQuery] = useState("");
  if (sources.length === 0)
    return (
      <p className="text-sm text-slate-600">
        No web check source is switched on for this organisation.
      </p>
    );
  const source = sources.find((s) => s.key === sourceKey) ?? sources[0];
  const e = state.fieldErrors;
  const error = state.error
    ? {
        ...state.error,
        message: requestErrorText(state.error.code) ?? state.error.message,
      }
    : null;

  return (
    <form action={formAction} noValidate className="space-y-3">
      {error && (
        <ErrorAlert title="The check could not be asked for" error={error} />
      )}
      <DialogField
        id={`${id}-source`}
        label="Where to look"
        error={e.source_key}
      >
        {(p) => (
          <select
            name="source_key"
            value={sourceKey}
            onChange={(ev) => setSourceKey(ev.target.value)}
            {...p}
          >
            {sources.map((s) => (
              <option key={s.key} value={s.key}>
                {s.title}
              </option>
            ))}
          </select>
        )}
      </DialogField>
      <DialogField
        id={`${id}-query`}
        label={QUERY_LABELS[source.kind]}
        error={e.query}
        hint={source.query_hint}
      >
        {(p) => (
          <input
            name="query"
            type="text"
            value={query}
            onChange={(ev) => setQuery(ev.target.value)}
            maxLength={200}
            autoComplete="off"
            {...p}
          />
        )}
      </DialogField>
      <button
        type="submit"
        className={buttonClass("secondary")}
        disabled={pending}
      >
        {pending ? "Asking…" : "Check"}
      </button>
    </form>
  );
}
