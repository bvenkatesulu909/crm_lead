import type { Metadata } from "next";

import { ContractForm } from "@/components/contract-form";
import { Card, Forbidden, PageHeader } from "@/components/ui";
import type { Account } from "@/lib/api-types";
import { initialFormState } from "@/lib/form-state";
import { canWriteContracts } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import { createContract } from "../actions";

export const metadata: Metadata = { title: "New contract" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function NewContractPage({
  searchParams,
}: PageProps<"/contracts/new">) {
  const me = await getMe();
  if (!canWriteContracts(me)) return <Forbidden />;
  const { account } = await searchParams;
  // "New contract" on an account page links here with ?account=<id>: show it as chosen. The API
  // decides whether this user may use that account; if not, the field simply starts empty.
  let defaultAccount: { id: string; name: string } | null = null;
  if (typeof account === "string" && UUID.test(account)) {
    try {
      const found = await apiFetch<Account>(`/accounts/${account}`);
      defaultAccount = { id: found.id, name: found.name };
    } catch {
      defaultAccount = null;
    }
  }

  return (
    <>
      <PageHeader
        title="New contract"
        description="Record the agreement as a draft. A manager activates it once the dates are set."
      />
      <Card className="max-w-4xl p-6">
        <ContractForm
          action={createContract}
          initialState={initialFormState}
          defaultAccount={defaultAccount}
          cancelHref={
            defaultAccount ? `/accounts/${defaultAccount.id}` : "/contracts"
          }
          submitLabel="Create draft"
        />
      </Card>
    </>
  );
}
