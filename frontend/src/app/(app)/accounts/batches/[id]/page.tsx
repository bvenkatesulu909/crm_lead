import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ActionDialog } from "@/components/action-dialog";
import {
  BatchAutoRefresh,
  BatchItemsTable,
  BatchSummary,
  RetryPanel,
} from "@/components/research-batch-views";
import {
  ButtonLink,
  Card,
  ErrorAlert,
  Forbidden,
  PageHeader,
  SuccessAlert,
} from "@/components/ui";
import { ApiError, toErrorInfo } from "@/lib/api-error";
import { initialDialogState } from "@/lib/dialog-state";
import { canRunResearchBatches } from "@/lib/permissions";
import { isRunning, isUuid, type BatchDetail } from "@/lib/research-batches";
import { apiFetch, getMe } from "@/lib/server/api";

import { cancelBatch } from "../actions";

export const metadata: Metadata = { title: "Research batch" };

export default async function ResearchBatchPage({
  params,
  searchParams,
}: PageProps<"/accounts/batches/[id]">) {
  const { id } = await params;
  const raw = await searchParams;
  if (!isUuid(id)) notFound();
  const me = await getMe();
  if (!canRunResearchBatches(me)) return <Forbidden />;
  let batch: BatchDetail;
  try {
    batch = await apiFetch<BatchDetail>(`/research-batches/${id}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    if (error instanceof ApiError && error.status === 403) return <Forbidden />;
    return (
      <>
        <PageHeader title="Research batch" />
        <ErrorAlert
          title="The batch could not be loaded"
          error={toErrorInfo(error)}
        />
      </>
    );
  }
  const running = isRunning(batch);
  return (
    <>
      <BatchAutoRefresh running={running} />
      <PageHeader
        title="Research batch"
        description={`${batch.account_count} ${batch.account_count === 1 ? "account" : "accounts"}, researched one at a time.`}
        actions={
          <div className="flex gap-2">
            {running && !batch.cancel_requested && (
              <ActionDialog
                triggerLabel="Stop the batch"
                title="Stop this batch?"
                description="The account being researched now is finished; the others are not run. Briefs already written are kept."
                confirmLabel="Stop the batch"
                confirmVariant="danger"
                action={cancelBatch.bind(null, batch.id)}
                initialState={initialDialogState}
                closeWhen={batch.cancel_requested}
              />
            )}
            <ButtonLink href="/accounts/batches" variant="secondary">
              All batches
            </ButtonLink>
          </div>
        }
      />
      {raw.done === "started" && (
        <div className="mb-4">
          <SuccessAlert>
            The batch started. This page updates itself while it runs.
          </SuccessAlert>
        </div>
      )}
      {raw.done === "cancel" && (
        <div className="mb-4">
          <SuccessAlert>
            The batch will stop after the account being researched now.
          </SuccessAlert>
        </div>
      )}
      <Card>
        <BatchSummary batch={batch} />
        <div className="border-t border-slate-200">
          <BatchItemsTable items={batch.items} />
        </div>
        <RetryPanel key={batch.status} batch={batch} />
      </Card>
    </>
  );
}
