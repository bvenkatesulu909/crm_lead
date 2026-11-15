"use client";

import { useActionState, useRef, useState } from "react";

import type {
  KnowledgeStartResult,
  KnowledgeUploadInfo,
} from "@/app/(app)/knowledge/actions";
import { DialogField } from "@/components/action-dialog";
import { ErrorAlert, buttonClass } from "@/components/ui";
import { UploadProgress } from "@/components/upload-progress";
import { directUpload } from "@/lib/direct-upload";
import { initialFormState, type FormState } from "@/lib/form-state";

/**
 * Upload a knowledge file; indexing happens in the background (status is shown in the list).
 * The file goes from the browser straight to the file store (ADR 0025); `start` and `finish`
 * only see its name and size.
 */
export function KnowledgeUploadForm({
  start,
  finish,
}: {
  start: (info: KnowledgeUploadInfo) => Promise<KnowledgeStartResult>;
  finish: (uploadId: string, previous: FormState) => Promise<FormState>;
}) {
  const [percent, setPercent] = useState<number | null>(null);
  // The file is read from the input itself (the File the person chose), not from FormData.
  const fileInput = useRef<HTMLInputElement>(null);

  async function action(
    previous: FormState,
    formData: FormData,
  ): Promise<FormState> {
    const values = {
      title: String(formData.get("title") ?? "").trim(),
      visibility: String(formData.get("visibility") ?? "internal"),
    };
    const refused = (
      fieldErrors: Record<string, string>,
      error: FormState["error"] = null,
    ): FormState => {
      setPercent(null);
      return { attempt: previous.attempt + 1, values, fieldErrors, error };
    };
    const file = fileInput.current?.files?.[0] ?? formData.get("file");
    if (!(file instanceof File) || file.size === 0)
      return refused({ file: "Choose a file." });
    setPercent(0);
    const outcome = await directUpload(
      file,
      () => start({ fileName: file.name, size: file.size, ...values }),
      (uploadId) => finish(uploadId, { ...previous, values }),
      setPercent,
    );
    if (!outcome.ok) return refused(outcome.fieldErrors, outcome.error);
    setPercent(null); // only reached when finishing failed (success navigates away)
    return outcome.result;
  }

  const [state, formAction, pending] = useActionState(action, initialFormState);
  const e = state.fieldErrors;

  return (
    <form key={state.attempt} action={formAction} className="space-y-4">
      {state.error && (
        <ErrorAlert
          title="The file could not be uploaded"
          error={state.error}
        />
      )}
      <DialogField
        id="knowledge-title"
        label="Title"
        optional
        error={e.title}
        hint="Leave empty to use the file name"
      >
        {(p) => (
          <input
            name="title"
            maxLength={200}
            defaultValue={state.values.title}
            {...p}
          />
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
            ref={fileInput}
            name="file"
            type="file"
            accept=".pdf,.docx,.txt,.md,.markdown"
            required
            {...p}
          />
        )}
      </DialogField>
      <UploadProgress percent={percent} />
      <button
        type="submit"
        disabled={pending}
        className={buttonClass("primary")}
      >
        {pending ? "Uploading…" : "Upload for indexing"}
      </button>
    </form>
  );
}
