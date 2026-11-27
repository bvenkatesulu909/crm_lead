"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import {
  estimateRetry,
  startRetry,
} from "@/app/(app)/accounts/batches/actions";
import { BatchConfirm } from "@/components/research-batch-confirm";
import { cx } from "@/components/ui";
import { formatTokens } from "@/lib/agents";
import { formatDateTime } from "@/lib/format";
import {
  BATCH_STATUS_LABELS,
  ITEM_STATUS_LABELS,
  failureText,
  gatheredText,
  isRunning,
  progress,
  retryable,
  type Batch,
  type BatchItem,
  type RetryWhich,
} from "@/lib/research-batches";

export const BATCH_REFRESH_MS = 5000;

/** While a batch runs the page looks again every few seconds; it stops once the batch ended. */
export function BatchAutoRefresh({
  running,
  refreshMs = BATCH_REFRESH_MS,
}: {
  running: boolean;
  refreshMs?: number;
}) {
  const router = useRouter();
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => router.refresh(), refreshMs);
    return () => clearInterval(timer);
  }, [running, router, refreshMs]);
  return null;
}

/** The batch's state, its progress and its tokens. */
export function BatchSummary({ batch }: { batch: Batch }) {
  const { ended, total, percent } = progress(batch);
  return (
    <div className="space-y-3 p-5">
      <p className="text-sm text-slate-700">
        <span className="font-medium text-slate-900">
          {BATCH_STATUS_LABELS[batch.status]}
        </span>
        {isRunning(batch) && batch.cancel_requested && (
          <> — stopping after the account being researched</>
        )}
        {" · "}started {formatDateTime(batch.created_at)}
        {batch.mine ? " by you" : " by a colleague"}
        {batch.finished_at && <> · ended {formatDateTime(batch.finished_at)}</>}
      </p>
      <div>
        <div
          role="progressbar"
          aria-label="Accounts done"
          aria-valuemin={0}
          aria-valuemax={total}
          aria-valuenow={ended}
          className="h-2 w-full overflow-hidden rounded-full bg-slate-200"
        >
          <div
            className="h-full bg-brand-600"
            style={{ width: `${percent}%` }}
          />
        </div>
        <p className="mt-1 text-sm text-slate-600">
          {ended} of {total} accounts ended
          {Object.entries(batch.counts)
            .filter(([, count]) => (count ?? 0) > 0)
            .map(
              ([status, count]) =>
                ` · ${count} ${ITEM_STATUS_LABELS[status as BatchItem["status"]].toLowerCase()}`,
            )
            .join("")}
        </p>
      </div>
      <p className="text-sm text-slate-600">
        {formatTokens(batch.tokens_used)} used of a cap of{" "}
        {formatTokens(batch.token_cap)}.
        {batch.not_available_count + batch.archived_count > 0 &&
          ` ${batch.not_available_count + batch.archived_count} chosen accounts were left out (not available to the person who started it, or archived).`}
      </p>
    </div>
  );
}

/** The table of a batch's accounts. A name is shown only when the viewer may read the account. */
export function BatchItemsTable({ items }: { items: BatchItem[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <caption className="sr-only">Accounts of this batch</caption>
        <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-600">
          <tr>
            <th scope="col" className="px-5 py-3">
              #
            </th>
            <th scope="col" className="px-5 py-3">
              Account
            </th>
            <th scope="col" className="px-5 py-3">
              State
            </th>
            <th scope="col" className="hidden px-5 py-3 md:table-cell">
              Brief
            </th>
            <th scope="col" className="hidden px-5 py-3 lg:table-cell">
              Tokens
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 bg-white">
          {items.map((item) => (
            <tr key={item.position}>
              <td className="px-5 py-3 text-slate-500">{item.position}</td>
              <th scope="row" className="px-5 py-3 text-left font-medium">
                {item.account_name === null ? (
                  <span className="text-slate-500">Not available to you</span>
                ) : (
                  <Link
                    href={`/accounts/${item.account_id}`}
                    className="text-brand-700 hover:underline"
                  >
                    {item.account_name}
                  </Link>
                )}
              </th>
              <td className="px-5 py-3">
                <span
                  className={cx(
                    "font-medium",
                    item.status === "failed" && "text-red-700",
                    (item.status === "done" || item.status === "reused") &&
                      "text-emerald-700",
                  )}
                >
                  {ITEM_STATUS_LABELS[item.status]}
                </span>
                {item.status === "failed" && (
                  <span className="block text-xs text-slate-600">
                    {failureText(item.failure_code)}
                  </span>
                )}
              </td>
              <td className="hidden px-5 py-3 text-slate-700 md:table-cell">
                {item.brief ? (
                  <>
                    {item.brief.sentences}{" "}
                    {item.brief.sentences === 1 ? "sentence" : "sentences"} from{" "}
                    {gatheredText(item.brief.gathered)}
                    {item.account_name !== null && (
                      <Link
                        href={`/accounts/${item.account_id}#account-research`}
                        className="ml-2 text-brand-700 hover:underline"
                      >
                        Read it
                      </Link>
                    )}
                  </>
                ) : (
                  "—"
                )}
              </td>
              <td className="hidden px-5 py-3 text-slate-700 lg:table-cell">
                {item.input_tokens + item.output_tokens > 0
                  ? formatTokens(item.input_tokens + item.output_tokens)
                  : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Try the failed or not-run accounts of an ended batch again: a NEW batch, confirmed like any. */
export function RetryPanel({ batch }: { batch: Batch }) {
  const { failed, notRun } = retryable(batch);
  const choices: [RetryWhich, string][] = [];
  if (failed > 0) choices.push(["failed", `The ${failed} failed`]);
  if (notRun > 0) choices.push(["not_run", `The ${notRun} not run`]);
  if (failed > 0 && notRun > 0) choices.push(["both", "Both"]);
  const [which, setWhich] = useState<RetryWhich>(choices[0]?.[0] ?? "failed");
  if (choices.length === 0) return null;
  return (
    <section
      aria-label="Try again"
      className="flex flex-wrap items-end gap-3 border-t border-slate-200 p-5"
    >
      <label className="text-sm text-slate-700">
        Accounts to try again
        <select
          value={which}
          onChange={(event) => setWhich(event.target.value as RetryWhich)}
          className="mt-1 block rounded-md border-0 px-3 py-2 text-sm ring-1 ring-inset ring-slate-300"
        >
          {choices.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <BatchConfirm
        label="Try them again"
        title="Try these accounts again in a new batch?"
        estimate={() => estimateRetry(batch.id, which)}
        start={(confirmed) => startRetry(batch.id, which, confirmed)}
      />
    </section>
  );
}
