"use client";

import { useActionState, useId, useState } from "react";

import { ErrorAlert, buttonClass } from "@/components/ui";
import type {
  BuyerMemory,
  BuyerMemoryItem,
  BuyerMemoryKey,
} from "@/lib/api-types";
import {
  MEMORY_TEXT_MAX,
  groupMemory,
  memorySummary,
  sourceLabel,
} from "@/lib/buyer-memory";
import { initialDialogState, type DialogState } from "@/lib/dialog-state";
import { formatDate } from "@/lib/format";

type FormAction = (
  state: DialogState,
  formData: FormData,
) => Promise<DialogState>;
type PlainAction = (state: DialogState) => Promise<DialogState>;

const field =
  "mt-1 block w-full rounded-md border-0 bg-white px-3 py-2 text-sm text-slate-900 ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-brand-600";

const labelOf = (keys: BuyerMemoryKey[], key: string) =>
  keys.find((k) => k.key === key)?.label ?? key;

/**
 * Buyer memory (ADR 0028): what we know about the buyer in three groups - facts (the buyer said it,
 * and we say where), assumptions (we think so, and say why) and what is still to ask. Everything
 * anyone wrote is shown as plain text. The forms send only the few fields the actions list.
 */
export function BuyerMemoryView({
  data,
  canWrite,
  addAction,
  confirmAction,
  copyAction,
}: {
  data: BuyerMemory;
  canWrite: boolean;
  addAction: FormAction;
  confirmAction: FormAction;
  copyAction: PlainAction;
}) {
  const groups = groupMemory(data);
  const nothing = data.current.length === 0;
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">{memorySummary(data)}</p>
      {nothing && (
        <p className="text-sm text-slate-600">
          Nothing recorded yet. Add what the buyer tells you, and the system
          shows what is still to ask.
        </p>
      )}
      {groups.facts.length > 0 && (
        <section aria-labelledby="memory-facts">
          <h3
            id="memory-facts"
            className="text-sm font-semibold text-slate-900"
          >
            Facts
          </h3>
          <ul className="mt-2 space-y-2">
            {groups.facts.map((i) => (
              <FactRow key={i.id} item={i} keys={data.keys} />
            ))}
          </ul>
        </section>
      )}
      {groups.assumptions.length > 0 && (
        <section aria-labelledby="memory-assumptions">
          <h3
            id="memory-assumptions"
            className="text-sm font-semibold text-slate-900"
          >
            Assumptions
          </h3>
          <p className="text-xs text-slate-500">
            We think so - not confirmed by the buyer.
          </p>
          <ul className="mt-2 space-y-2">
            {groups.assumptions.map((i) => (
              <AssumptionRow
                key={i.id}
                item={i}
                keys={data.keys}
                canWrite={canWrite}
                action={confirmAction}
              />
            ))}
          </ul>
        </section>
      )}
      {data.gaps.length > 0 && (
        <section aria-labelledby="memory-gaps">
          <h3 id="memory-gaps" className="text-sm font-semibold text-slate-900">
            Still to ask
          </h3>
          <ul className="mt-2 flex flex-wrap gap-2">
            {data.gaps.map((g) => (
              <li
                key={g.key}
                className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-700"
              >
                {g.label}
              </li>
            ))}
          </ul>
        </section>
      )}
      {canWrite && (
        <div className="space-y-3 border-t border-slate-100 pt-4">
          <AddDetail keys={data.keys} action={addAction} />
          <CopyFromLead action={copyAction} />
        </div>
      )}
      {data.history.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer font-medium text-slate-700">
            Earlier entries ({data.history.length})
          </summary>
          <ul className="mt-2 space-y-2">
            {data.history.map((i) => (
              <li key={i.id} className="rounded-md bg-slate-50 p-2 text-xs">
                <span className="font-medium">
                  {labelOf(data.keys, i.key)}:
                </span>{" "}
                {i.value}{" "}
                <span className="text-slate-500">
                  ({i.status === "fact" ? "fact" : "assumption"},{" "}
                  {formatDate(i.created_at)})
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
      <p className="text-xs text-slate-500">
        Do not record religion, caste, health, politics or ID numbers here.
      </p>
    </div>
  );
}

function FactRow({
  item,
  keys,
}: {
  item: BuyerMemoryItem;
  keys: BuyerMemoryKey[];
}) {
  return (
    <li className="rounded-md border border-slate-200 p-3 text-sm">
      <p>
        <span className="font-medium text-slate-900">
          {labelOf(keys, item.key)}
        </span>
      </p>
      <p className="whitespace-pre-line text-slate-900">{item.value}</p>
      <p className="mt-1 text-xs text-slate-500">
        {sourceLabel(item.source)}
        {item.quote ? ` - "${item.quote}"` : ""} · {formatDate(item.created_at)}
      </p>
    </li>
  );
}

function AssumptionRow({
  item,
  keys,
  canWrite,
  action,
}: {
  item: BuyerMemoryItem;
  keys: BuyerMemoryKey[];
  canWrite: boolean;
  action: FormAction;
}) {
  const [open, setOpen] = useState(false);
  // React empties a form after its action. Each field keeps its text in state and is remounted
  // after every attempt with that text as its default, so a refusal never loses what was typed.
  const [quote, setQuote] = useState("");
  const [corrected, setCorrected] = useState("");
  const [state, formAction, pending] = useActionState(
    action,
    initialDialogState,
  );
  const id = useId();
  return (
    <li className="rounded-md border border-amber-200 bg-amber-50/40 p-3 text-sm">
      <p>
        <span className="font-medium text-slate-900">
          {labelOf(keys, item.key)}
        </span>
      </p>
      <p className="whitespace-pre-line text-slate-900">{item.value}</p>
      <p className="mt-1 text-xs text-slate-600">
        Why we think so: {item.reason} · {formatDate(item.created_at)}
      </p>
      {canWrite && !open && (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className={`${buttonClass("secondary")} mt-2`}
        >
          Confirm
        </button>
      )}
      {canWrite && open && (
        <form action={formAction} className="mt-3 space-y-3">
          <input type="hidden" name="item_id" value={item.id} />
          {state.error && (
            <ErrorAlert title="Could not confirm" error={state.error} />
          )}
          <div>
            <label htmlFor={`${id}-quote`} className="text-sm font-medium">
              What did the buyer say?
            </label>
            <textarea
              id={`${id}-quote`}
              name="quote"
              key={state.attempt}
              rows={2}
              maxLength={MEMORY_TEXT_MAX}
              defaultValue={quote}
              onChange={(e) => setQuote(e.target.value)}
              className={field}
            />
            {state.fieldErrors.quote && (
              <p className="mt-1 text-xs text-red-700">
                {state.fieldErrors.quote}
              </p>
            )}
          </div>
          <div>
            <label htmlFor={`${id}-value`} className="text-sm font-medium">
              Correct the detail (optional)
            </label>
            <input
              id={`${id}-value`}
              name="value"
              key={state.attempt}
              maxLength={MEMORY_TEXT_MAX}
              defaultValue={corrected}
              onChange={(e) => setCorrected(e.target.value)}
              className={field}
            />
          </div>
          <div className="flex gap-2">
            <button type="submit" disabled={pending} className={buttonClass()}>
              {pending ? "Saving…" : "Confirm as fact"}
            </button>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className={buttonClass("secondary")}
            >
              Cancel
            </button>
          </div>
        </form>
      )}
    </li>
  );
}

function AddDetail({
  keys,
  action,
}: {
  keys: BuyerMemoryKey[];
  action: FormAction;
}) {
  // The form is built on first open, so a page full of cards does not hold hidden duplicates.
  const [open, setOpen] = useState(false);
  return (
    <details
      onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}
    >
      <summary className="cursor-pointer text-sm font-medium text-brand-700">
        Add a detail
      </summary>
      {open && <AddDetailForm keys={keys} action={action} />}
    </details>
  );
}

function AddDetailForm({
  keys,
  action,
}: {
  keys: BuyerMemoryKey[];
  action: FormAction;
}) {
  const [state, formAction, pending] = useActionState(
    action,
    initialDialogState,
  );
  const [status, setStatus] = useState<"fact" | "assumption">("fact");
  // See the confirm form: the text is kept in state and the fields remount with it after each attempt.
  const [topic, setTopic] = useState("");
  const [value, setValue] = useState("");
  const [quote, setQuote] = useState("");
  const [reason, setReason] = useState("");
  const id = useId();
  return (
    <form action={formAction} className="mt-3 space-y-3">
      {state.error && <ErrorAlert title="Could not save" error={state.error} />}
      <div>
        <label htmlFor={`${id}-key`} className="text-sm font-medium">
          What is it about?
        </label>
        <select
          id={`${id}-key`}
          name="key"
          key={state.attempt}
          defaultValue={topic}
          onChange={(e) => setTopic(e.target.value)}
          className={field}
        >
          <option value="" disabled>
            Choose…
          </option>
          {keys.map((k) => (
            <option key={k.key} value={k.key}>
              {k.label}
            </option>
          ))}
        </select>
        {state.fieldErrors.key && (
          <p className="mt-1 text-xs text-red-700">{state.fieldErrors.key}</p>
        )}
      </div>
      <fieldset className="space-y-1">
        <legend className="text-sm font-medium">How do we know?</legend>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="radio"
            name="status"
            value="fact"
            key={state.attempt}
            defaultChecked={status === "fact"}
            onChange={() => setStatus("fact")}
          />
          The buyer told us
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="radio"
            name="status"
            value="assumption"
            key={state.attempt}
            defaultChecked={status === "assumption"}
            onChange={() => setStatus("assumption")}
          />
          We think so (not confirmed)
        </label>
      </fieldset>
      <div>
        <label htmlFor={`${id}-value`} className="text-sm font-medium">
          The detail
        </label>
        <input
          id={`${id}-value`}
          name="value"
          key={state.attempt}
          maxLength={MEMORY_TEXT_MAX}
          defaultValue={value}
          onChange={(e) => setValue(e.target.value)}
          className={field}
        />
        {state.fieldErrors.value && (
          <p className="mt-1 text-xs text-red-700">{state.fieldErrors.value}</p>
        )}
      </div>
      {status === "fact" ? (
        <div>
          <label htmlFor={`${id}-quote`} className="text-sm font-medium">
            What the buyer said
          </label>
          <textarea
            id={`${id}-quote`}
            name="quote"
            key={state.attempt}
            rows={2}
            maxLength={MEMORY_TEXT_MAX}
            defaultValue={quote}
            onChange={(e) => setQuote(e.target.value)}
            className={field}
          />
          {state.fieldErrors.quote && (
            <p className="mt-1 text-xs text-red-700">
              {state.fieldErrors.quote}
            </p>
          )}
        </div>
      ) : (
        <div>
          <label htmlFor={`${id}-reason`} className="text-sm font-medium">
            Why do we think so?
          </label>
          <textarea
            id={`${id}-reason`}
            name="reason"
            key={state.attempt}
            rows={2}
            maxLength={MEMORY_TEXT_MAX}
            defaultValue={reason}
            onChange={(e) => setReason(e.target.value)}
            className={field}
          />
          {state.fieldErrors.reason && (
            <p className="mt-1 text-xs text-red-700">
              {state.fieldErrors.reason}
            </p>
          )}
        </div>
      )}
      <button type="submit" disabled={pending} className={buttonClass()}>
        {pending ? "Saving…" : "Save detail"}
      </button>
    </form>
  );
}

function CopyFromLead({ action }: { action: PlainAction }) {
  const [state, formAction, pending] = useActionState(
    action,
    initialDialogState,
  );
  return (
    <form action={formAction} className="space-y-2">
      {state.error && <ErrorAlert title="Could not copy" error={state.error} />}
      <button
        type="submit"
        disabled={pending}
        className={buttonClass("secondary")}
      >
        {pending ? "Copying…" : "Copy from the lead form"}
      </button>
      <p className="text-xs text-slate-500">
        Adds the budget, property type and area from the lead form as facts, for
        the details that have no answer yet.
      </p>
    </form>
  );
}
