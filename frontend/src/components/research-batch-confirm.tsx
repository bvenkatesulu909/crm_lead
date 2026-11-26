"use client";

import { useId, useRef, useState, useTransition } from "react";

import { ErrorAlert, buttonClass } from "@/components/ui";
import { formatCost, formatTokens } from "@/lib/agents";
import type { ApiErrorInfo } from "@/lib/api-error";
import {
  batchErrorText,
  type BatchEstimate,
  type EstimateResult,
  type StartFailed,
} from "@/lib/research-batches";

/** An error box in plain words for a refused estimate or start. */
function Refusal({ title, error }: { title: string; error: ApiErrorInfo }) {
  return (
    <ErrorAlert
      title={title}
      error={{ ...error, message: batchErrorText(error) }}
    />
  );
}

/** The figures a person confirms before a batch starts. Everything is a number from the API. */
export function EstimateView({ estimate }: { estimate: BatchEstimate }) {
  const cost = formatCost(estimate.estimated_cost_usd);
  const rows: [string, string][] = [
    ["Accounts in the batch", String(estimate.accounts)],
    ["Recent brief used (no cost)", String(estimate.reused)],
    ["Accounts the AI will read", String(estimate.calling_model)],
    ["Not available to you (left out)", String(estimate.not_available)],
    ["Archived (left out)", String(estimate.archived)],
    ["Usual use", `about ${formatTokens(estimate.typical_tokens)}`],
    ["At most", formatTokens(estimate.upper_bound_tokens)],
    ["The batch stops before it passes", formatTokens(estimate.cap_tokens)],
  ];
  if (estimate.monthly_tokens_left !== null)
    rows.push([
      "Left of this month's budget",
      formatTokens(estimate.monthly_tokens_left),
    ]);
  return (
    <div className="space-y-3">
      <dl className="grid grid-cols-[1fr_auto] gap-x-6 gap-y-1 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-slate-600">{label}</dt>
            <dd className="text-right font-medium text-slate-900">{value}</dd>
          </div>
        ))}
      </dl>
      {cost && (
        <p className="text-sm text-slate-700">
          Estimated cost at most: {cost} (an estimate from the configured
          prices, not a bill).
        </p>
      )}
      <p className="text-sm text-slate-600">
        The accounts are researched one at a time, each on its own. You can stop
        the batch at any time; what is done is kept.
      </p>
    </div>
  );
}

/**
 * A button that asks for an estimate, shows it in a dialog and starts only when the person
 * confirms. The estimate is fetched when the button is pressed, so the figures are fresh; the
 * start sends back the figure shown and the API refuses it when the cost has moved.
 */
export function BatchConfirm({
  label,
  title,
  disabled = false,
  disabledReason,
  estimate,
  start,
}: {
  label: string;
  title: string;
  disabled?: boolean;
  disabledReason?: string;
  estimate: () => Promise<EstimateResult>;
  start: (confirmed: number) => Promise<StartFailed>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [found, setFound] = useState<BatchEstimate | null>(null);
  const [error, setError] = useState<ApiErrorInfo | null>(null);
  const [asking, startAsking] = useTransition();
  const [starting, startStarting] = useTransition();

  const ask = () =>
    startAsking(async () => {
      setFound(null);
      setError(null);
      const result = await estimate();
      if (result.ok) setFound(result.estimate);
      else setError(result.error);
      dialog.current?.showModal();
    });

  const confirm = () => {
    if (found === null) return;
    const shown = found.upper_bound_tokens;
    startStarting(async () => {
      // A start that works moves to the batch's page; we only get here when it was refused.
      const result = await start(shown);
      setFound(null);
      setError(result.error);
    });
  };

  return (
    <>
      <button
        type="button"
        className={buttonClass("primary")}
        disabled={disabled || asking}
        title={disabled ? disabledReason : undefined}
        onClick={ask}
      >
        {asking ? "Working out the cost…" : label}
      </button>
      <dialog
        ref={dialog}
        aria-labelledby={titleId}
        className="w-full max-w-lg rounded-lg p-0 shadow-xl backdrop:bg-slate-900/40"
      >
        <div className="space-y-4 p-6">
          <h2 id={titleId} className="text-lg font-semibold text-slate-900">
            {title}
          </h2>
          {error && <Refusal title="The batch cannot start" error={error} />}
          {found && <EstimateView estimate={found} />}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              className={buttonClass("secondary")}
              onClick={() => dialog.current?.close()}
            >
              {found ? "Cancel" : "Close"}
            </button>
            {found && (
              <button
                type="button"
                className={buttonClass("primary")}
                disabled={starting}
                onClick={confirm}
              >
                {starting ? "Starting…" : "Start research"}
              </button>
            )}
          </div>
        </div>
      </dialog>
    </>
  );
}
