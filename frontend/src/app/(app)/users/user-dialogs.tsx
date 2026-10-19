"use client";

import { useId, useState } from "react";

import { ActionDialog, DialogField } from "@/components/action-dialog";
import { STAFF_ROLES, type StaffRole } from "@/lib/api-types";
import { type DialogState, initialDialogState } from "@/lib/dialog-state";
import { ROLE_LABELS } from "@/lib/permissions";

type Bound = (state: DialogState, formData: FormData) => Promise<DialogState>;

/** What each role may do, shown when choosing one. */
const ROLE_HINTS: Record<StaffRole, string> = {
  tenant_admin: "Everything, including users and billing.",
  sales_manager: "All sales, orders and billing.",
  sales_agent: "Only their own leads, accounts and orders.",
  support_agent: "Support tickets; reads accounts, orders and invoices.",
};

function RoleSelect({
  errors,
  defaultValue = "sales_agent",
  withCustomer = false,
  onChange,
}: {
  errors: Record<string, string>;
  defaultValue?: string;
  withCustomer?: boolean;
  onChange?: (role: string) => void;
}) {
  // Several dialogs on one page each have a Role field: ids must be unique per dialog.
  const id = useId();
  return (
    <DialogField id={`${id}-role`} label="Role" error={errors.role}>
      {(props) => (
        <select name="role" defaultValue={defaultValue} onChange={(e) => onChange?.(e.target.value)} {...props}>
          {STAFF_ROLES.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]} — {ROLE_HINTS[r]}</option>)}
          {withCustomer && <option value="customer">Customer (portal) — sees only chosen accounts</option>}
        </select>
      )}
    </DialogField>
  ); // prettier-ignore
}

function PersonFields({ errors }: { errors: Record<string, string> }) {
  const id = useId();
  return (
    <>
      <DialogField id={`${id}-email`} label="E-mail" error={errors.email}>
        {(props) => <input name="email" type="email" maxLength={320} autoComplete="off" {...props} />}
      </DialogField>
      <div className="grid gap-4 sm:grid-cols-2">
        <DialogField id={`${id}-first`} label="First name" error={errors.first_name}>
          {(props) => <input name="first_name" maxLength={100} {...props} />}
        </DialogField>
        <DialogField id={`${id}-last`} label="Last name" error={errors.last_name}>
          {(props) => <input name="last_name" maxLength={100} {...props} />}
        </DialogField>
      </div>
    </>
  ); // prettier-ignore
}

export function AddStaffUserButton({ action }: { action: Bound }) {
  return (
    <ActionDialog
      triggerLabel="Add staff member"
      triggerVariant="primary"
      title="Add a staff member"
      description="They receive an e-mail to set their own password. You never see or choose it."
      confirmLabel="Add and send invitation"
      action={action}
      initialState={initialDialogState}
    >
      {(errors) => (
        <>
          <PersonFields errors={errors} />
          <RoleSelect errors={errors} />
        </>
      )}
    </ActionDialog>
  );
}

export function ChangeRoleButton({
  name,
  role,
  action,
}: {
  name: string;
  role: string;
  action: Bound;
}) {
  return (
    <ActionDialog
      triggerLabel="Change role"
      title={`Change the role of ${name}`}
      description="Takes effect the next time their sign-in refreshes (within about 5 minutes)."
      confirmLabel="Change role"
      action={action}
      initialState={initialDialogState}
    >
      {(errors) => <RoleSelect errors={errors} defaultValue={role} />}
    </ActionDialog>
  );
}

export function ConfirmButton({
  label,
  title,
  description,
  action,
  danger = false,
}: {
  label: string;
  title: string;
  description: string;
  action: Bound;
  danger?: boolean;
}) {
  return (
    <ActionDialog
      triggerLabel={label}
      triggerVariant={danger ? "danger" : "secondary"}
      title={title}
      description={description}
      confirmLabel={label}
      confirmVariant={danger ? "danger" : "primary"}
      action={action}
      initialState={initialDialogState}
    />
  );
}

export function ApproveRequestButton({
  name,
  email,
  accounts,
  action,
}: {
  name: string;
  email: string;
  accounts: { id: string; name: string }[];
  action: Bound;
}) {
  const [role, setRole] = useState("sales_agent");
  return (
    <ActionDialog
      triggerLabel="Approve"
      triggerVariant="primary"
      title={`Approve ${name}`}
      description={<>Signed up as <strong>{email}</strong> (verified). Choose what they may do in your organisation.</>}
      confirmLabel="Approve"
      action={action}
      initialState={initialDialogState}
    >
      {(errors) => (
        <>
          <RoleSelect errors={errors} withCustomer defaultValue={role} onChange={setRole} />
          {role === "customer" && (
            <fieldset>
              <legend className="text-sm font-medium text-slate-700">Accounts they may see</legend>
              {errors.account_ids && <p role="alert" className="mt-1 text-sm text-red-700">{errors.account_ids}</p>}
              <div className="mt-2 max-h-48 space-y-1 overflow-y-auto">
                {accounts.map((a) => (
                  <label key={a.id} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" name="account_ids" value={a.id} /> {a.name}
                  </label>
                ))}
              </div>
            </fieldset>
          )}
        </>
      )}
    </ActionDialog>
  ); // prettier-ignore
}
