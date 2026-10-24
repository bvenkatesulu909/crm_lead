import type { Metadata } from "next";

import { OpportunityForm } from "@/components/opportunity-form";
import { Card, Forbidden, PageHeader } from "@/components/ui";
import { initialFormState } from "@/lib/form-state";
import {
  canManageOpportunities,
  canReadContacts,
  canWriteOpportunities,
} from "@/lib/permissions";
import { getMe } from "@/lib/server/api";
import {
  accountOption,
  contactOptions,
  salesOwnerOptions,
} from "@/lib/server/options";

import { createOpportunity } from "../actions";

export const metadata: Metadata = { title: "New opportunity" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function NewOpportunityPage({
  searchParams,
}: PageProps<"/opportunities/new">) {
  const { account } = await searchParams;
  const me = await getMe();
  if (!canWriteOpportunities(me)) return <Forbidden />;
  const [defaultAccount, contacts, owners] = await Promise.all([
    accountOption(account),
    canReadContacts(me)
      ? contactOptions().catch(() => [])
      : Promise.resolve([]),
    canManageOpportunities(me)
      ? salesOwnerOptions()
      : Promise.resolve(undefined),
  ]);
  const fromAccount =
    typeof account === "string" && UUID.test(account) ? account : undefined;

  return (
    <>
      <PageHeader
        title="New opportunity"
        description="A potential sale to one of your customer accounts."
      />
      <Card className="max-w-3xl p-6">
        <OpportunityForm
          action={createOpportunity}
          initialState={initialFormState}
          accounts={[]}
          searchAccounts
          defaultAccount={defaultAccount}
          contacts={contacts}
          owners={owners}
          defaultAccountId={fromAccount}
          cancelHref={
            fromAccount ? `/accounts/${fromAccount}` : "/opportunities"
          }
          submitLabel="Create opportunity"
        />
      </Card>
    </>
  );
}
