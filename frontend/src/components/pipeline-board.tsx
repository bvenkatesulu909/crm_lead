"use client";

import Link from "next/link";
import { useState, useTransition } from "react";

import { ErrorAlert, cx } from "@/components/ui";
import type { ApiErrorInfo } from "@/lib/api-error";
import {
  OPEN_STAGES,
  type BoardColumn,
  type Opportunity,
  type OpenStage,
} from "@/lib/api-types";
import { formatAmounts } from "@/lib/dashboard";
import { STAGE_LABELS } from "@/lib/pipeline";

type Move = (
  id: string,
  version: number,
  stage: string,
) => Promise<{ error: ApiErrorInfo | null }>;

const money = (o: Opportunity) =>
  o.amount === null
    ? "No value yet"
    : formatAmounts([{ currency: o.currency, amount: o.amount }]);

function Card({
  opp,
  accountName,
  ownerName,
  canMove,
  onMove,
  busy,
}: {
  opp: Opportunity;
  accountName: string;
  ownerName: string;
  canMove: boolean;
  onMove: (o: Opportunity, stage: OpenStage) => void;
  busy: boolean;
}) {
  const closing =
    opp.expected_close_date &&
    new Date(`${opp.expected_close_date}T00:00:00`).toLocaleDateString(
      "en-GB",
      { day: "numeric", month: "short", year: "numeric" },
    );
  return (
    <li
      draggable={canMove}
      onDragStart={(e) => {
        e.dataTransfer.setData("text/plain", opp.id);
        e.dataTransfer.effectAllowed = "move";
      }}
      className={cx(
        "rounded-lg border border-slate-200 bg-white p-3 shadow-sm",
        canMove && "cursor-grab active:cursor-grabbing",
        busy && "opacity-50",
      )}
      data-testid="deal-card"
    >
      <Link href={`/opportunities/${opp.id}`} className="block text-sm font-medium text-slate-900 hover:text-brand-700 hover:underline">
        {opp.name}
      </Link>
      <p className="mt-0.5 truncate text-xs text-slate-500">{accountName}</p>
      <p className="mt-2 text-sm font-semibold text-slate-900">{money(opp)}</p>
      <p className="text-xs text-slate-500">
        {closing ? `Closes ${closing}` : "No close date"} · {ownerName}
      </p>
      {canMove && (
        <label className="mt-2 block text-xs text-slate-600">
          <span className="sr-only">Move {opp.name} to</span>
          <select
            value=""
            disabled={busy}
            onChange={(e) => e.target.value && onMove(opp, e.target.value as OpenStage)}
            className="mt-1 block w-full rounded-md border-0 bg-slate-50 px-2 py-1 text-xs ring-1 ring-inset ring-slate-200"
          >
            <option value="">Move to…</option>
            {OPEN_STAGES.filter((s) => s !== opp.stage).map((s) => (
              <option key={s} value={s}>{STAGE_LABELS[s]}</option>
            ))}
          </select>
        </label>
      )}
    </li>
  ); // prettier-ignore
}

/**
 * Kanban board of the open pipeline. Drag a card to another column, or use its "Move to"
 * menu (keyboard and screen-reader friendly). Every move goes through the API, which checks
 * permissions and the version; the board then reloads from the server.
 */
export function PipelineBoard({
  columns,
  accountNames,
  ownerNames,
  writable,
  move,
}: {
  columns: BoardColumn[];
  accountNames: Record<string, string>;
  ownerNames: Record<string, string>;
  /** IDs of deals this user may move (display only; the API decides). */
  writable: string[];
  move: Move;
}) {
  const [error, setError] = useState<ApiErrorInfo | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const [, startTransition] = useTransition();
  const byId = new Map(columns.flatMap((c) => c.items).map((o) => [o.id, o]));

  const onMove = (opp: Opportunity, stage: OpenStage) => {
    if (opp.stage === stage) return;
    setBusy(opp.id);
    setError(null);
    startTransition(async () => {
      const result = await move(opp.id, opp.version, stage);
      setBusy(null);
      if (result.error) setError(result.error);
    });
  };

  return (
    <>
      {error && <div className="mb-4"><ErrorAlert title="The deal could not be moved" error={error} /></div>}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {columns.map((column) => (
          <section
            key={column.stage}
            aria-label={`${STAGE_LABELS[column.stage]} column`}
            onDragOver={(e) => { e.preventDefault(); setOver(column.stage); }}
            onDragLeave={() => setOver(null)}
            onDrop={(e) => {
              e.preventDefault();
              setOver(null);
              const opp = byId.get(e.dataTransfer.getData("text/plain"));
              if (opp && writable.includes(opp.id)) onMove(opp, column.stage as OpenStage);
            }}
            className={cx("flex min-h-48 flex-col rounded-xl bg-slate-100 p-3", over === column.stage && "ring-2 ring-brand-500")}
          >
            <header className="mb-3">
              <div className="flex items-baseline justify-between gap-2">
                <h2 className="text-sm font-semibold text-slate-900">{STAGE_LABELS[column.stage]}</h2>
                <span className="text-xs text-slate-500">{column.count} · {column.probability}%</span>
              </div>
              <p className="text-xs text-slate-600">{formatAmounts(column.value)}</p>
              <p className="text-xs text-slate-500">Weighted {formatAmounts(column.weighted)}</p>
            </header>
            {column.items.length === 0 ? (
              <p className="rounded-lg border border-dashed border-slate-300 p-4 text-center text-xs text-slate-500">No deals</p>
            ) : (
              <ol className="space-y-2">
                {column.items.map((o) => (
                  <Card
                    key={o.id}
                    opp={o}
                    accountName={accountNames[o.account_id] ?? "Account"}
                    ownerName={o.owner_id ? (ownerNames[o.owner_id] ?? "Former colleague") : "No owner"}
                    canMove={writable.includes(o.id)}
                    onMove={onMove}
                    busy={busy === o.id}
                  />
                ))}
              </ol>
            )}
            {column.count > column.items.length && (
              <p className="mt-2 text-xs text-slate-500">
                Showing {column.items.length} of {column.count}. Narrow the board with the filters.
              </p>
            )}
          </section>
        ))}
      </div>
    </>
  ); // prettier-ignore
}
