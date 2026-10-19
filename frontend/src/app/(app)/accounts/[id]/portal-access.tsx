"use client";

import { ActionDialog, DialogField } from "@/components/action-dialog";
import { Card } from "@/components/ui";
import type { PortalUser } from "@/lib/api-types";
import { type DialogState, initialDialogState } from "@/lib/dialog-state";

type Bound = (state: DialogState, formData: FormData) => Promise<DialogState>;

/** Who can see this account in the customer portal, with invite / remove for allowed staff. */
export function PortalAccessCard({
  accountName,
  users,
  invite,
  revoke,
}: {
  accountName: string;
  users: PortalUser[];
  /** Present only if the user may invite (the API checks again). */
  invite?: Bound;
  revoke?: Record<string, Bound>;
}) {
  return (
    <Card>
      <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-5 py-4">
        <h2 className="text-base font-semibold text-slate-900">Portal access</h2>
        {invite && (
          <ActionDialog
            triggerLabel="Invite"
            title={`Invite a contact of ${accountName}`}
            description="They get an e-mail to set a password and then see this account (and only accounts they are invited to) in the customer portal."
            confirmLabel="Send invitation"
            action={invite}
            initialState={initialDialogState}
          >
            {(errors) => (
              <>
                <DialogField id="invite-email" label="E-mail" error={errors.email}>
                  {(props) => <input name="email" type="email" maxLength={320} autoComplete="off" {...props} />}
                </DialogField>
                <div className="grid gap-4 sm:grid-cols-2">
                  <DialogField id="invite-first" label="First name" error={errors.first_name}>
                    {(props) => <input name="first_name" maxLength={100} {...props} />}
                  </DialogField>
                  <DialogField id="invite-last" label="Last name" error={errors.last_name}>
                    {(props) => <input name="last_name" maxLength={100} {...props} />}
                  </DialogField>
                </div>
              </>
            )}
          </ActionDialog>
        )}
      </div>
      {users.length === 0 ? (
        <p className="px-5 py-6 text-sm text-slate-600">No customer can see this account in the portal.</p>
      ) : (
        <ul className="divide-y divide-slate-100">
          {users.map((u) => (
            <li key={u.id} className="flex items-center justify-between gap-3 px-5 py-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-slate-900">{u.display_name}</p>
                <p className="truncate text-xs text-slate-500">
                  {u.email} · {u.last_login_at ? "has signed in" : "invited, not signed in yet"}
                </p>
              </div>
              {revoke?.[u.id] && (
                <ActionDialog
                  triggerLabel="Remove"
                  triggerVariant="danger"
                  title={`Remove ${u.display_name}'s access?`}
                  description={`They will no longer see ${accountName} in the portal. Their login and other accounts stay.`}
                  confirmLabel="Remove access"
                  confirmVariant="danger"
                  action={revoke[u.id]}
                  initialState={initialDialogState}
                />
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  ); // prettier-ignore
}
