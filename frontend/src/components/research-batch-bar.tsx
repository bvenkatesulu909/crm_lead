"use client";

import { useState } from "react";

import {
  estimateBatch,
  startBatch,
} from "@/app/(app)/accounts/batches/actions";
import { BatchConfirm } from "@/components/research-batch-confirm";
import {
  MAX_BATCH_ACCOUNTS,
  type BatchSelection,
} from "@/lib/research-batches";

export const SELECTION_FORM = "research-batch-selection";

/** The ticked rows of the Accounts list (the boxes belong to the form by its id). */
export function tickedAccounts(doc: Document = document): string[] {
  const form = doc.getElementById(SELECTION_FORM);
  if (!(form instanceof HTMLFormElement)) return [];
  return new FormData(form).getAll("account_id").map(String);
}

/** A box in the table's header that ticks or unticks every row on this page. */
export function TickAll() {
  return (
    <input
      type="checkbox"
      aria-label="Tick every account on this page"
      className="h-4 w-4 rounded border-slate-300"
      onChange={(event) => {
        const boxes = document.querySelectorAll<HTMLInputElement>(
          `input[form="${SELECTION_FORM}"][name="account_id"]`,
        );
        boxes.forEach((box) => {
          box.checked = event.target.checked;
        });
      }}
    />
  );
}

/** One row's box: it only says which account; the API decides whether it may be researched. */
export function TickBox({ id, name }: { id: string; name: string }) {
  return (
    <input
      type="checkbox"
      form={SELECTION_FORM}
      name="account_id"
      value={id}
      aria-label={`Tick ${name}`}
      className="h-4 w-4 rounded border-slate-300"
    />
  );
}

/**
 * Research many accounts at once (ADR 0042): the ticked rows, or every account of the saved
 * filter in use. Shown only to people who may start a batch; the API checks again.
 */
export function ResearchBatchBar({
  savedFilter,
}: {
  /** The saved filter the list is showing now, if any. */
  savedFilter: { id: string; name: string } | null;
}) {
  const [again, setAgain] = useState(false);
  const rows = (): BatchSelection => ({
    source: "rows",
    saved_filter_id: null,
    account_ids: tickedAccounts(),
    research_again: again,
  });
  const filter = (id: string): BatchSelection => ({
    source: "filter",
    saved_filter_id: id,
    account_ids: [],
    research_again: again,
  });
  return (
    <section
      aria-label="Research many accounts"
      className="flex flex-wrap items-center gap-3 border-t border-slate-200 px-5 py-3"
    >
      <form id={SELECTION_FORM} className="hidden" />
      <h2 className="text-sm font-medium text-slate-700">AI research</h2>
      <BatchConfirm
        label="Research ticked accounts"
        title="Research the ticked accounts?"
        estimate={() => estimateBatch(rows())}
        start={(confirmed) => startBatch(rows(), confirmed)}
      />
      {savedFilter && (
        <BatchConfirm
          label={`Research every account of “${savedFilter.name}”`}
          title={`Research every account of “${savedFilter.name}”?`}
          estimate={() => estimateBatch(filter(savedFilter.id))}
          start={(confirmed) => startBatch(filter(savedFilter.id), confirmed)}
        />
      )}
      <label className="flex items-center gap-2 text-sm text-slate-700">
        <input
          type="checkbox"
          checked={again}
          onChange={(event) => setAgain(event.target.checked)}
          className="h-4 w-4 rounded border-slate-300"
        />
        Research again even if researched in the last day
      </label>
      <span className="text-xs text-slate-500">
        At most {MAX_BATCH_ACCOUNTS} accounts per batch.
      </span>
    </section>
  );
}
