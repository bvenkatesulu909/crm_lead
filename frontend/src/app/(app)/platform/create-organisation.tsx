"use client";

import { ActionDialog, DialogField } from "@/components/action-dialog";
import { type DialogState, initialDialogState } from "@/lib/dialog-state";

export function CreateOrganisationButton({
  action,
}: {
  action: (state: DialogState, formData: FormData) => Promise<DialogState>;
}) {
  return (
    <ActionDialog
      triggerLabel="New organisation"
      triggerVariant="primary"
      title="Create an organisation"
      description="Its first Tenant Admin receives an e-mail to set a password and then manages everyone else. You won't see the organisation's business data."
      confirmLabel="Create organisation"
      action={action}
      initialState={initialDialogState}
    >
      {(errors) => (
        <>
          <DialogField id="org-name" label="Organisation name" error={errors.name}>
            {(props) => <input name="name" maxLength={200} {...props} />}
          </DialogField>
          <DialogField id="org-slug" label="Short name" hint="Used internally, e.g. acme-ltd." error={errors.slug}>
            {(props) => <input name="slug" maxLength={63} autoComplete="off" {...props} />}
          </DialogField>
          <DialogField id="org-admin-email" label="First admin's e-mail" error={errors.admin_email}>
            {(props) => <input name="admin_email" type="email" maxLength={320} {...props} />}
          </DialogField>
          <div className="grid gap-4 sm:grid-cols-2">
            <DialogField id="org-admin-first" label="First name" error={errors.admin_first_name}>
              {(props) => <input name="admin_first_name" maxLength={100} {...props} />}
            </DialogField>
            <DialogField id="org-admin-last" label="Last name" error={errors.admin_last_name}>
              {(props) => <input name="admin_last_name" maxLength={100} {...props} />}
            </DialogField>
          </div>
        </>
      )}
    </ActionDialog>
  ); // prettier-ignore
}
