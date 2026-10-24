import type { Metadata } from "next";

import { AccountForm } from "@/components/customer-forms";
import { Card, Forbidden, PageHeader } from "@/components/ui";
import { initialFormState } from "@/lib/form-state";
import { canManageAccounts, canWriteAccounts } from "@/lib/permissions";
import { getMe } from "@/lib/server/api";
import { accountOption, salesOwnerOptions } from "@/lib/server/options";

import { createAccount } from "../actions";

export const metadata: Metadata = { title: "New account" };

export default async function NewAccountPage({
  searchParams,
}: PageProps<"/accounts/new">) {
  const { parent } = await searchParams;
  const me = await getMe();
  // Friendly early answer; the API would refuse anyway.
  if (!canWriteAccounts(me)) return <Forbidden />;
  const manager = canManageAccounts(me);
  const [defaultParent, owners] = await Promise.all([
    accountOption(parent),
    manager ? salesOwnerOptions() : Promise.resolve(undefined),
  ]);

  return (
    <>
      <PageHeader
        title="New account"
        description={
          manager
            ? "A customer organisation. Choose the sales rep who owns it, or keep the default."
            : "A customer organisation. You will be its owner."
        }
      />
      <Card className="max-w-3xl p-6">
        <AccountForm
          action={createAccount}
          initialState={initialFormState}
          defaultParent={defaultParent}
          owners={owners}
          cancelHref="/accounts"
          submitLabel="Create account"
        />
      </Card>
    </>
  );
}
