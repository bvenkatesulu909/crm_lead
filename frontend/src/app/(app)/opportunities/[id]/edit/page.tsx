import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { OpportunityForm } from "@/components/opportunity-form";
import { Card, Forbidden, PageHeader } from "@/components/ui";
import { ApiError } from "@/lib/api-error";
import type { Account, Opportunity } from "@/lib/api-types";
import { initialFormState } from "@/lib/form-state";
import {
  canManageOpportunities,
  canReadContacts,
  canWriteOpportunities,
} from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";
import { contactOptions, salesOwnerOptions } from "@/lib/server/options";

import { updateOpportunity } from "../../actions";

export const metadata: Metadata = { title: "Edit opportunity" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function EditOpportunityPage({
  params,
}: PageProps<"/opportunities/[id]/edit">) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  const me = await getMe();
  if (!canWriteOpportunities(me)) return <Forbidden />;
  let opp: Opportunity;
  try {
    opp = await apiFetch<Opportunity>(`/opportunities/${id}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
  if (opp.stage === "closed_won" || opp.stage === "closed_lost")
    return (
      <Forbidden message="This deal is closed. A manager can reopen it if it needs to change." />
    );
  const [account, contacts, owners] = await Promise.all([
    apiFetch<Account>(`/accounts/${opp.account_id}`).catch(() => null),
    canReadContacts(me)
      ? contactOptions().catch(() => [])
      : Promise.resolve([]),
    canManageOpportunities(me)
      ? salesOwnerOptions()
      : Promise.resolve(undefined),
  ]);

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link href={`/opportunities/${opp.id}`} className="font-medium text-brand-700 hover:underline">
          ← {opp.name}
        </Link>
      </nav>
      <PageHeader title="Edit opportunity" description={opp.name} />
      <Card className="max-w-3xl p-6">
        <OpportunityForm
          action={updateOpportunity.bind(null, opp.id, opp.version)}
          initialState={initialFormState}
          opportunity={opp}
          accounts={[{ id: opp.account_id, name: account?.name ?? "Account" }]}
          contacts={contacts}
          owners={owners}
          cancelHref={`/opportunities/${opp.id}`}
          submitLabel="Save changes"
        />
      </Card>
    </>
  ); // prettier-ignore
}
