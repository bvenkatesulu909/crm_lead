"use client";

import { useActionState } from "react";

import { DialogField } from "@/components/action-dialog";
import { ErrorAlert, buttonClass } from "@/components/ui";
import { initialFormState, type FormState } from "@/lib/form-state";

/** Upload a knowledge file; indexing happens in the background (status is shown in the list). */
export function KnowledgeUploadForm({
  action,
}: {
  action: (state: FormState, formData: FormData) => Promise<FormState>;
}) {
  const [state, formAction, pending] = useActionState(action, initialFormState);
  const e = state.fieldErrors;

  return (
    <form key={state.attempt} action={formAction} className="space-y-4">
      {state.error && (
        <ErrorAlert title="The file could not be uploaded" error={state.error} />
      )}
      <DialogField
        id="knowledge-title"
        label="Title"
        optional
        error={e.title}
        hint="Leave empty to use the file name"
      >
        {(p) => (
          <input name="title" maxLength={200} defaultValue={state.values.title} {...p} />
        )}
      </DialogField>
      <DialogField
        id="knowledge-visibility"
        label="Who can see this?"
        error={e.visibility}
        hint="Staff only, or also customers in the portal (once portal search exists)"
      >
        {(p) => (
          <select
            name="visibility"
            defaultValue={state.values.visibility ?? "internal"}
            {...p}
          >
            <option value="internal">Staff only</option>
            <option value="customer_visible">Staff and customers</option>
          </select>
        )}
      </DialogField>
      <DialogField
        id="knowledge-file"
        label="File"
        error={e.file}
        hint="PDF, Word (.docx), TXT or Markdown - up to 20 MB"
      >
        {(p) => (
          <input
            name="file"
            type="file"
            accept=".pdf,.docx,.txt,.md,.markdown"
            required
            {...p}
          />
        )}
      </DialogField>
      <button type="submit" disabled={pending} className={buttonClass("primary")}>
        {pending ? "Uploading…" : "Upload for indexing"}
      </button>
    </form>
  );
}
