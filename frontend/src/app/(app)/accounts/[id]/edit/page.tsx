import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AccountForm } from "@/components/customer-forms";
import { Card, Forbidden, PageHeader } from "@/components/ui";
import { ApiError } from "@/lib/api-error";
import type { Account } from "@/lib/api-types";
import { initialFormState } from "@/lib/form-state";
import { canManageAccounts, canWriteAccounts } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";
import { accountOption, salesOwnerOptions } from "@/lib/server/options";

import { updateAccount } from "../../actions";

export const metadata: Metadata = { title: "Edit account" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function EditAccountPage({
  params,
}: PageProps<"/accounts/[id]/edit">) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  const me = await getMe();
  if (!canWriteAccounts(me)) return <Forbidden />;
  let account: Account;
  try {
    account = await apiFetch<Account>(`/accounts/${id}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
  // Display only: agents may edit their own accounts. The API checks again on save.
  if (!canManageAccounts(me) && account.owner_id !== me.user_id)
    return <Forbidden message="You may view this account but not change it." />;
  const manager = canManageAccounts(me);
  const [parent, owners] = await Promise.all([
    accountOption(account.parent_account_id ?? undefined),
    manager ? salesOwnerOptions() : Promise.resolve(undefined),
  ]);

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link
          href={`/accounts/${account.id}`}
          className="font-medium text-brand-700 hover:underline"
        >
          ← {account.name}
        </Link>
      </nav>
      <PageHeader title="Edit account" description={account.name} />
      <Card className="max-w-3xl p-6">
        <AccountForm
          action={updateAccount.bind(null, account.id, account.version)}
          initialState={initialFormState}
          account={account}
          defaultParent={parent}
          owners={owners}
          cancelHref={`/accounts/${account.id}`}
          submitLabel="Save changes"
        />
      </Card>
    </>
  );
}
