"use client";

import { ActionDialog, DialogField } from "@/components/action-dialog";
import type { DialogState } from "@/lib/dialog-state";
import { initialDialogState } from "@/lib/dialog-state";

type Action = (state: DialogState, formData: FormData) => Promise<DialogState>;

const ACCEPT =
  ".pdf,.png,.jpg,.jpeg,.gif,.txt,.csv,.docx,.xlsx,.pptx,.odt,.ods";

/** Upload a file. A file with the same name as an existing one becomes its next version. */
export function UploadDocumentDialog({
  action,
  allowCustomerVisible,
}: {
  action: Action;
  allowCustomerVisible: boolean;
}) {
  return (
    <ActionDialog triggerLabel="Upload" triggerVariant="secondary" title="Upload a document"
      description="PDF, images, text/CSV, Word, Excel, PowerPoint or OpenDocument - up to 20 MB. A file with the same name as an existing one is saved as its new version."
      confirmLabel="Upload" action={action} initialState={initialDialogState}>
      {(errors) => (
        <>
          <DialogField id="doc-file" label="File" error={errors.file}>
            {(p) => <input type="file" name="file" accept={ACCEPT} required {...p} />}
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
