"use client";

import { useRef, useState } from "react";

import type { StartResult, UploadInfo } from "@/app/(app)/documents/actions";
import { ActionDialog, DialogField } from "@/components/action-dialog";
import { UploadProgress } from "@/components/upload-progress";
import type { DialogState } from "@/lib/dialog-state";
import { initialDialogState } from "@/lib/dialog-state";
import { directUpload } from "@/lib/direct-upload";

type Action = (state: DialogState, formData: FormData) => Promise<DialogState>;

const ACCEPT =
  ".pdf,.png,.jpg,.jpeg,.gif,.txt,.csv,.docx,.xlsx,.pptx,.odt,.ods";

/**
 * Upload a file. A file with the same name as an existing one becomes its next version.
 * The file goes from the browser straight to the file store (ADR 0025): `start` and `finish`
 * are Server Actions that only ever see the file's name and size, never its bytes.
 */
export function UploadDocumentDialog({
  start,
  finish,
  allowCustomerVisible,
}: {
  start: (info: UploadInfo) => Promise<StartResult>;
  finish: (uploadId: string, previous: DialogState) => Promise<DialogState>;
  allowCustomerVisible: boolean;
}) {
  const [percent, setPercent] = useState<number | null>(null);
  // The file is read from the input itself (the File the person chose), not from FormData.
  const fileInput = useRef<HTMLInputElement>(null);

  async function action(
    previous: DialogState,
    formData: FormData,
  ): Promise<DialogState> {
    const refused = (
      fieldErrors: Record<string, string>,
      error: DialogState["error"] = null,
    ): DialogState => {
      setPercent(null);
      return { attempt: previous.attempt + 1, fieldErrors, error };
    };
    const file = fileInput.current?.files?.[0] ?? formData.get("file");
    if (!(file instanceof File) || file.size === 0)
      return refused({ file: "Choose a file." });
    setPercent(0);
    const outcome = await directUpload(
      file,
      () =>
        start({
          fileName: file.name,
          size: file.size,
          description: String(formData.get("description") ?? ""),
          customerVisible:
            allowCustomerVisible && formData.get("customer_visible") === "on",
        }),
      (uploadId) => finish(uploadId, previous),
      setPercent,
    );
    if (!outcome.ok) return refused(outcome.fieldErrors, outcome.error);
    setPercent(null); // only reached when finishing failed (success navigates away)
    return outcome.result;
  }

  return (
    <ActionDialog triggerLabel="Upload" triggerVariant="secondary" title="Upload a document"
      description="PDF, images, text/CSV, Word, Excel, PowerPoint or OpenDocument - up to 20 MB. A file with the same name as an existing one is saved as its new version."
      confirmLabel="Upload" action={action} initialState={initialDialogState}>
      {(errors) => (
        <>
          <DialogField id="doc-file" label="File" error={errors.file}>
            {(p) => <input ref={fileInput} type="file" name="file" accept={ACCEPT} required {...p} />}
          </DialogField>
          <DialogField id="doc-description" label="Description" optional error={errors.description}>
            {(p) => <input name="description" maxLength={500} {...p} />}
          </DialogField>
          {allowCustomerVisible && (
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input type="checkbox" name="customer_visible" className="h-4 w-4 rounded border-slate-300 text-brand-600" />
              Visible to the customer in the portal
            </label>
          )}
          <UploadProgress percent={percent} />
        </>
      )}
    </ActionDialog>
  ); // prettier-ignore
}

export function DeleteDocumentDialog({
  action,
  name,
  versions,
}: {
  action: Action;
  name: string;
  versions: number;
}) {
  return (
    <ActionDialog triggerLabel="Delete" triggerVariant="secondary" title={`Delete ${name}?`}
      description={versions > 1 ? `All ${versions} versions are deleted. This can't be undone.` : "This can't be undone."}
      confirmLabel="Delete" confirmVariant="danger" action={action} initialState={initialDialogState} />
  ); // prettier-ignore
}
