"use client";

import { ActionDialog } from "@/components/action-dialog";
import type { DialogState } from "@/lib/dialog-state";
import { initialDialogState } from "@/lib/dialog-state";

type Action = (state: DialogState, formData: FormData) => Promise<DialogState>;

/** Deactivate a template (agents no longer see it) or bring it back. */
export function TemplateActiveDialog({
  action,
  name,
  active,
}: {
  action: Action;
  name: string;
  active: boolean;
}) {
  return active ? (
    <ActionDialog triggerLabel="Deactivate" title={`Deactivate ${name}?`}
      description="Agents won't see it any more when they write an e-mail. E-mails already written keep their text. You can reactivate it later."
      confirmLabel="Deactivate" confirmVariant="danger" action={action} initialState={initialDialogState} />
  ) : (
    <ActionDialog triggerLabel="Reactivate" title={`Reactivate ${name}?`}
      description="Agents can use it again when they write an e-mail."
      confirmLabel="Reactivate" action={action} initialState={initialDialogState} />
  ); // prettier-ignore
}
