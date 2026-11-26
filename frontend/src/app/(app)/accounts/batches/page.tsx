import type { Metadata } from "next";
import Link from "next/link";

import { Pagination } from "@/components/pagination";
import {
  ButtonLink,
  Card,
  EmptyState,
  ErrorAlert,
  Forbidden,
  PageHeader,
} from "@/components/ui";
import { formatTokens } from "@/lib/agents";
import { ApiError, toErrorInfo } from "@/lib/api-error";
import { formatDateTime } from "@/lib/format";
import { canRunResearchBatches } from "@/lib/permissions";
import {
  BATCH_STATUS_LABELS,
  progress,
  type BatchPage,
} from "@/lib/research-batches";
import { apiFetch, getMe } from "@/lib/server/api";

export const metadata: Metadata = { title: "Research batches" };

const PAGE_SIZE = 20;

export default async function ResearchBatchesPage({
  searchParams,
}: PageProps<"/accounts/batches">) {
  const raw = await searchParams;
  const me = await getMe();
  if (!canRunResearchBatches(me)) return <Forbidden />;
  const page = Math.max(1, Number.parseInt(String(raw.page ?? "1"), 10) || 1);
  let data: BatchPage;
  try {
    data = await apiFetch<BatchPage>(
      `/research-batches?limit=${PAGE_SIZE}&offset=${(page - 1) * PAGE_SIZE}`,
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) return <Forbidden />;
    return (
      <>
        <PageHeader title="Research batches" />
        <ErrorAlert
          title="Research batches could not be loaded"
          error={toErrorInfo(error)}
        />
      </>
    );
  }
  return (
    <>
      <PageHeader
        title="Research batches"
        description="Accounts researched by the AI many at a time, newest first. Each account is researched on its own."
        actions={
          <ButtonLink href="/accounts" variant="secondary">
            Back to accounts
          </ButtonLink>
        }
      />
      <Card>
        {data.items.length === 0 ? (
          <EmptyState
            title="No research batches yet"
            description="Tick accounts on the Accounts list, or apply a saved filter, then choose Research."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <caption className="sr-only">Research batches</caption>
              <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-600">
                <tr>
                  <th scope="col" className="px-5 py-3">
                    Started
                  </th>
                  <th scope="col" className="px-5 py-3">
                    State
                  </th>
                  <th scope="col" className="px-5 py-3">
                    Accounts
                  </th>
                  <th scope="col" className="hidden px-5 py-3 md:table-cell">
                    Tokens
                  </th>
                  <th scope="col" className="hidden px-5 py-3 md:table-cell">
                    By
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {data.items.map((batch) => {
                  const { ended, total } = progress(batch);
                  return (
                    <tr key={batch.id} className="hover:bg-slate-50">
                      <th
                        scope="row"
                        className="px-5 py-3 text-left font-medium"
                      >
                        <Link
                          href={`/accounts/batches/${batch.id}`}
                          className="text-brand-700 hover:underline"
                        >
                          {formatDateTime(batch.created_at)}
                        </Link>
                      </th>
                      <td className="px-5 py-3 text-slate-700">
                        {BATCH_STATUS_LABELS[batch.status]}
                      </td>
                      <td className="px-5 py-3 text-slate-700">
                        {ended} of {total} ended
                      </td>
                      <td className="hidden px-5 py-3 text-slate-700 md:table-cell">
                        {formatTokens(batch.tokens_used)}
                      </td>
                      <td className="hidden px-5 py-3 text-slate-700 md:table-cell">
                        {batch.mine ? "You" : "A colleague"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {data.total > 0 && (
          <div className="border-t border-slate-200">
            <Pagination
              total={data.total}
              page={page}
              pageSize={PAGE_SIZE}
              hrefForPage={(p) => `/accounts/batches?page=${p}`}
            />
          </div>
        )}
      </Card>
    </>
  );
}
