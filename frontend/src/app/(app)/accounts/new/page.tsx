import type { Metadata } from "next";

import { AccountForm } from "@/components/customer-forms";
import { Card, Forbidden, PageHeader } from "@/components/ui";
import { initialFormState } from "@/lib/form-state";
import { canManageAccounts, canWriteAccounts } from "@/lib/permissions";
import { getMe } from "@/lib/server/api";
import { accountOptions, salesOwnerOptions } from "@/lib/server/options";

import { createAccount } from "../actions";

export const metadata: Metadata = { title: "New account" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function NewAccountPage({
  searchParams,
}: PageProps<"/accounts/new">) {
  const { parent } = await searchParams;
  const me = await getMe();
  // Friendly early answer; the API would refuse anyway.
  if (!canWriteAccounts(me)) return <Forbidden />;
  const manager = canManageAccounts(me);
  const [parents, owners] = await Promise.all([
    accountOptions(),
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
          parents={parents}
          defaultParentId={
            typeof parent === "string" && UUID.test(parent) ? parent : undefined
          }
          owners={owners}
          cancelHref="/accounts"
          submitLabel="Create account"
        />
      </Card>
    </>
  );
}
