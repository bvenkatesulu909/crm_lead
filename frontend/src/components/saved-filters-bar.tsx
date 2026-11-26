"use client";

import Link from "next/link";
import { useState } from "react";

import {
  deleteSavedFilter,
  saveFilter,
} from "@/app/(app)/accounts/saved-filter-actions";
import { ActionDialog } from "@/components/action-dialog";
import { cx } from "@/components/ui";
import { initialDialogState } from "@/lib/dialog-state";
import {
  hasHiddenConditions,
  hrefForSavedFilter,
  matchesList,
  type SavedFilter,
} from "@/lib/saved-filters";

type ListParams = {
  q: string;
  status: string;
  segment: string;
  country: string;
  lifecycle: string;
};

const field =
  "mt-1 block w-full rounded-md border-0 bg-white px-3 py-2 text-sm text-slate-900 ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-brand-600";

/**
 * The saved filters of the Accounts list: choose one to apply it, save the current filter under a
 * name, delete your own. Everything shown is plain text. Whether you may share or delete is decided
 * by the API; `canShare` only hides a box that would be refused.
 */
export function SavedFiltersBar({
  filters,
  list,
  filtered,
  canShare,
}: {
  filters: SavedFilter[];
  list: ListParams;
  /** True when the list currently has at least one condition. */
  filtered: boolean;
  canShare: boolean;
}) {
  const alreadySaved = filters.some((f) => matchesList(f, list));
  return (
    <section aria-label="Saved filters" className="px-5 pb-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="mr-1 text-sm font-medium text-slate-700">
          Saved filters
        </h2>
        {filters.length === 0 && (
          <span className="text-sm text-slate-500">None yet.</span>
        )}
        {filters.map((filter) => {
          const selected = matchesList(filter, list);
          return (
            <span
              key={filter.id}
              className={cx(
                "inline-flex items-center gap-1 rounded-full py-1 pl-3 pr-2 text-sm ring-1 ring-inset",
                selected
                  ? "bg-brand-600 text-white ring-brand-600"
                  : "bg-white text-slate-700 ring-slate-300",
              )}
            >
              <Link
                href={hrefForSavedFilter(filter)}
                aria-current={selected ? "true" : undefined}
                className="hover:underline"
              >
                {filter.name}
              </Link>
              {filter.shared && (
                <span className="text-xs opacity-80">
                  {filter.mine ? "(shared)" : "(team)"}
                </span>
              )}
              {hasHiddenConditions(filter) && (
                <span
                  className="text-xs opacity-80"
                  title="This filter has conditions this screen cannot show."
                >
                  (partly shown)
                </span>
              )}
              {filter.mine && (
                <ActionDialog
                  triggerLabel="Delete"
                  title={`Delete the filter "${filter.name}"?`}
                  description="Only the saved filter is deleted. No account is changed."
                  confirmLabel="Delete filter"
                  confirmVariant="danger"
                  action={deleteSavedFilter.bind(null, filter.id)}
                  initialState={initialDialogState}
                />
              )}
            </span>
          );
        })}
        {filtered && !alreadySaved && (
          <SaveDialog list={list} canShare={canShare} />
        )}
      </div>
    </section>
  );
}

/**
 * The dialog that saves the filter in use. The name and the share choice live in state because the
 * dialog builds a fresh form after every attempt: without this a refused save (a name already in
 * use) would send the person back to an empty box.
 */
function SaveDialog({
  list,
  canShare,
}: {
  list: ListParams;
  canShare: boolean;
}) {
  const [name, setName] = useState("");
  const [shared, setShared] = useState(false);
  return (
    <ActionDialog
      triggerLabel="Save this filter"
      title="Save this filter"
      description="Give the filter you are using a name so you can come back to it in one click."
      confirmLabel="Save filter"
      action={saveFilter}
      initialState={initialDialogState}
    >
      {(errors) => (
        <>
          {(["q", "status", "segment", "country", "lifecycle"] as const).map(
            (key) => (
              <input key={key} type="hidden" name={key} value={list[key]} />
            ),
          )}
          <label
            htmlFor="saved-filter-name"
            className="text-sm font-medium text-slate-700"
          >
            Name
          </label>
          <input
            id="saved-filter-name"
            name="name"
            required
            maxLength={80}
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="For example: Hyderabad enterprise"
            className={field}
            aria-invalid={errors.name ? true : undefined}
          />
          {errors.name && (
            <p className="mt-1 text-sm text-red-700">{errors.name}</p>
          )}
          {canShare && (
            <label className="mt-3 flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                name="shared"
                checked={shared}
                onChange={(event) => setShared(event.target.checked)}
              />
              Share with everyone in my organisation
            </label>
          )}
        </>
      )}
    </ActionDialog>
  );
}
