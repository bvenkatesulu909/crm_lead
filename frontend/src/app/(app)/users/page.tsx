import type { Metadata } from "next";

import {
  Card,
  ErrorAlert,
  Forbidden,
  PageHeader,
  SuccessAlert,
  cx,
} from "@/components/ui";
import { ApiError, toErrorInfo } from "@/lib/api-error";
import type { AccessRequest, AccountPage, AdminUser } from "@/lib/api-types";
import { formatDate, formatDateTime } from "@/lib/format";
import { ROLE_LABELS, canManageUsers } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import {
  addStaffUser,
  approveRequest,
  changeRole,
  regenerateCode,
  rejectRequest,
  resendInvite,
  setActive,
} from "./actions";
import {
  AddStaffUserButton,
  ApproveRequestButton,
  ChangeRoleButton,
  ConfirmButton,
} from "./user-dialogs";

export const metadata: Metadata = { title: "Users" };

const DONE: Record<string, string> = {
  added:
    "The staff member was added. They received an e-mail to set their password.",
  role: "The role was changed. It applies at their next sign-in refresh.",
  deactivated: "The user was deactivated and signed out everywhere.",
  reactivated: "The user can sign in again.",
  resent: "The invitation e-mail was sent again.",
  code: "A new sign-up code was created. The old one no longer works.",
  approved: "The request was approved.",
  rejected: "The request was rejected.",
};

export default async function UsersPage({ searchParams }: PageProps<"/users">) {
  const [me, query] = await Promise.all([getMe(), searchParams]);
  let users: AdminUser[];
  let requests: AccessRequest[] = [];
  let code: string | null = null;
  let accounts: AccountPage["items"] = [];
  const manage = canManageUsers(me);
  try {
    [users, requests, code, accounts] = await Promise.all([
      apiFetch<AdminUser[]>("/tenant/users"),
      manage
        ? apiFetch<AccessRequest[]>("/tenant/access-requests")
        : Promise.resolve([]),
      manage
        ? apiFetch<{ signup_code: string }>("/tenant/signup-code").then(
            (c) => c.signup_code,
          )
        : Promise.resolve(null),
      manage
        ? apiFetch<AccountPage>("/accounts?limit=200").then((a) => a.items)
        : Promise.resolve([]),
    ]);
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) return <Forbidden />;
    return (
      <>
        <PageHeader title="Users" />
        <ErrorAlert
          title="Users could not be loaded"
          error={toErrorInfo(error)}
        />
      </>
    );
  }
  const done = typeof query.done === "string" ? DONE[query.done] : undefined;
  const staff = users.filter((u) => u.user_type === "staff");
  const customers = users.filter((u) => u.user_type === "customer");
  const accountName = (id: string) =>
    accounts.find((a) => a.id === id)?.name ?? "Account";

  return (
    <>
      <PageHeader
        title="Users"
        description={`People who can sign in to ${me.tenant_name ?? "your organisation"}.`}
        actions={manage && <AddStaffUserButton action={addStaffUser} />}
      />
      {done && <div className="mb-4"><SuccessAlert>{done}</SuccessAlert></div>}

      {manage && (
        <div className="mb-6 grid gap-6 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">
              Waiting for approval {requests.length > 0 && <span className="ml-1 rounded-full bg-amber-100 px-2 text-sm text-amber-900">{requests.length}</span>}
            </h2>
            {requests.length === 0 ? (
              <p className="px-5 py-6 text-sm text-slate-600">No one is waiting. People who sign up with your code appear here.</p>
            ) : (
              <ul aria-label="Access requests" className="divide-y divide-slate-100">
                {requests.map((r) => (
                  <li key={r.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
                    <div>
                      <p className="font-medium text-slate-900">{r.display_name}</p>
                      <p className="text-xs text-slate-500">{r.email} · asked {formatDateTime(r.created_at)}</p>
                    </div>
                    <div className="flex gap-2">
                      <ApproveRequestButton name={r.display_name} email={r.email} accounts={accounts.map((a) => ({ id: a.id, name: a.name }))} action={approveRequest.bind(null, r.id)} />
                      <ConfirmButton label="Reject" danger title={`Reject ${r.display_name}?`} description="They keep no access. They can ask again later with a code." action={rejectRequest.bind(null, r.id)} />
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card className="p-5">
            <h2 className="text-base font-semibold text-slate-900">Sign-up code</h2>
            <p className="mt-1 text-sm text-slate-600">Give this code to colleagues or customers who create their own account. You still approve every request.</p>
            <p aria-label="Sign-up code" className="my-4 rounded-md bg-slate-100 p-3 text-center font-mono text-lg font-semibold tracking-widest text-slate-900">{code}</p>
            <ConfirmButton label="Create new code" title="Create a new sign-up code?" description="The current code stops working immediately. Requests already sent are kept." action={regenerateCode} />
          </Card>
        </div>
      )}

      <Card className="mb-6">
        <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">Staff</h2>
        <UserTable users={staff} meId={me.user_id} manage={manage} kind="staff" accountName={accountName} />
      </Card>
      <Card>
        <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">Customer portal users</h2>
        <p className="px-5 pt-3 text-sm text-slate-600">Invite customers from an account&apos;s page (&quot;Portal access&quot;).</p>
        <UserTable users={customers} meId={me.user_id} manage={manage} kind="customer" accountName={accountName} />
      </Card>
    </>
  ); // prettier-ignore
}

function UserTable({
  users,
  meId,
  manage,
  kind,
  accountName,
}: {
  users: AdminUser[];
  meId: string | null;
  manage: boolean;
  kind: "staff" | "customer";
  accountName: (id: string) => string;
}) {
  if (users.length === 0)
    return <p className="px-5 py-6 text-sm text-slate-600">Nobody yet.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-600">
          <tr>
            <th scope="col" className="px-5 py-3">Name</th>
            <th scope="col" className="px-5 py-3">{kind === "staff" ? "Role" : "Accounts"}</th>
            <th scope="col" className="hidden px-5 py-3 md:table-cell">Last sign-in</th>
            <th scope="col" className="px-5 py-3">Status</th>
            {manage && <th scope="col" className="px-5 py-3"><span className="sr-only">Actions</span></th>}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 bg-white">
          {users.map((u) => {
            const self = u.id === meId;
            return (
              <tr key={u.id}>
                <th scope="row" className="px-5 py-3 text-left font-normal">
                  <span className="font-medium text-slate-900">{u.display_name}</span>{self && <span className="ml-1 text-xs text-slate-500">(you)</span>}
                  <span className="block text-xs text-slate-500">{u.email}</span>
                </th>
                <td className="px-5 py-3 text-slate-700">
                  {kind === "staff" ? u.roles.map((r) => ROLE_LABELS[r] ?? r).join(", ") || "—" : u.portal_account_ids.map(accountName).join(", ") || "—"}
                </td>
                <td className="hidden whitespace-nowrap px-5 py-3 text-slate-700 md:table-cell">{u.last_login_at ? formatDate(u.last_login_at) : "Never"}</td>
                <td className="px-5 py-3">
                  <span className={cx("inline-flex rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset", u.is_active ? "bg-emerald-50 text-emerald-800 ring-emerald-200" : "bg-slate-100 text-slate-600 ring-slate-300")}>
                    {u.is_active ? "Active" : "Deactivated"}
                  </span>
                </td>
                {manage && (
                  <td className="px-5 py-3">
                    {!self && (
                      <div role="group" aria-label={`Actions for ${u.display_name}`} className="flex flex-wrap justify-end gap-2">
                        {kind === "staff" && u.is_active && <ChangeRoleButton name={u.display_name} role={u.roles[0] ?? "sales_agent"} action={changeRole.bind(null, u.id)} />}
                        {u.is_active && !u.last_login_at && <ConfirmButton label="Resend invitation" title={`Send the invitation to ${u.email} again?`} description="The new link is valid for 72 hours." action={resendInvite.bind(null, u.id)} />}
                        {u.is_active ? (
                          <ConfirmButton label="Deactivate" danger title={`Deactivate ${u.display_name}?`} description="They are signed out everywhere and can no longer sign in. Their records stay." action={setActive.bind(null, u.id, false)} />
                        ) : (
                          <ConfirmButton label="Reactivate" title={`Reactivate ${u.display_name}?`} description="They can sign in again with their existing password." action={setActive.bind(null, u.id, true)} />
                        )}
                      </div>
                    )}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  ); // prettier-ignore
}
