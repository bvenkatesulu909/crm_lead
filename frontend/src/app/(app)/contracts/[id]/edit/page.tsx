import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ContractForm } from "@/components/contract-form";
import { Card, Forbidden, PageHeader } from "@/components/ui";
import { ApiError } from "@/lib/api-error";
import type { Contract } from "@/lib/api-types";
import { initialFormState } from "@/lib/form-state";
import { canWriteContracts } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import { updateContract } from "../../actions";

export const metadata: Metadata = { title: "Edit contract" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function EditContractPage({
  params,
}: PageProps<"/contracts/[id]/edit">) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  const me = await getMe();
  if (!canWriteContracts(me)) return <Forbidden />;
  let contract: Contract;
  try {
    contract = await apiFetch<Contract>(`/contracts/${id}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    if (error instanceof ApiError && error.status === 403) return <Forbidden />;
    throw error;
  }
  // Only drafts and active contracts can be changed (the API refuses the rest as well).
  if (contract.status !== "draft" && contract.status !== "active")
    return (
      <Card className="max-w-2xl p-6 text-sm text-slate-700">
        <p>A {contract.status} contract can no longer be changed.</p>
        <p className="mt-3">
          <Link
            href={`/contracts/${contract.id}`}
            className="text-brand-700 hover:underline"
          >
            Back to the contract
          </Link>
        </p>
      </Card>
    );
  const mode = contract.status === "draft" ? "draft" : "active";

  return (
    <>
      <PageHeader
        title={`Edit ${contract.label}`}
        description={contract.title}
      />
      <Card className="max-w-4xl p-6">
        <ContractForm
          action={updateContract.bind(
            null,
            contract.id,
            contract.version,
            mode,
          )}
          initialState={initialFormState}
          contract={contract}
          cancelHref={`/contracts/${contract.id}`}
          submitLabel="Save changes"
        />
      </Card>
    </>
  );
}
