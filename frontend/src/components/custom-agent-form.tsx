"use client";

import { useActionState, useId, useState } from "react";

import { DialogField } from "@/components/action-dialog";
import { ErrorAlert, buttonClass } from "@/components/ui";
import type { CustomAgentMenus } from "@/lib/api-types";
import {
  kindAllowed,
  recordNoun,
  recordTypeOf,
  splitList,
} from "@/lib/custom-agents";
import type { FormState } from "@/lib/form-state";

const GROUPS = [
  { type: "lead", heading: "About a lead" },
  { type: "account", heading: "About an account" },
  { type: "deal", heading: "About a deal" },
] as const;

/**
 * The definition of a custom agent (ADR 0034): a name, what it is for, an instruction in plain
 * words, what it may READ and what it may SUGGEST. Reading and suggesting come only from fixed
 * menus, and an agent works on one kind of record. The checks here only help; the API checks
 * everything again (the menus, the lengths, words that try to change the AI's safety rules).
 */
export function CustomAgentForm({
  menus,
  initial,
  initialState,
  action,
  submitLabel,
}: {
  menus: CustomAgentMenus;
  initial: {
    name: string;
    purpose: string;
    instruction: string;
    read_sets: string[];
    suggestion_kinds: string[];
  };
  initialState: FormState;
  action: (state: FormState, formData: FormData) => Promise<FormState>;
  submitLabel: string;
}) {
  const id = useId();
  const [state, formAction, pending] = useActionState(action, initialState);
  // After a refusal the typed values come back in `state.values`; keep them on screen.
  const kept = state.values;
  const [name, setName] = useState(kept.name ?? initial.name);
  const [purpose, setPurpose] = useState(kept.purpose ?? initial.purpose);
  const [instruction, setInstruction] = useState(
    kept.instruction ?? initial.instruction,
  );
  const [readSets, setReadSets] = useState<string[]>(
    kept.read_sets !== undefined
      ? splitList(kept.read_sets)
      : initial.read_sets,
  );
  const [kinds, setKinds] = useState<string[]>(
    kept.suggestion_kinds !== undefined
      ? splitList(kept.suggestion_kinds)
      : initial.suggestion_kinds,
  );
  const type = recordTypeOf(readSets, menus.read_sets);
  const toggle = (list: string[], key: string) =>
    list.includes(key) ? list.filter((k) => k !== key) : [...list, key];

  return (
    <form action={formAction} noValidate className="space-y-5">
      {state.error && (
        <ErrorAlert title="The agent could not be saved" error={state.error} />
      )}
      <DialogField
        id={`${id}-name`}
        label="Name"
        error={state.fieldErrors.name}
        hint={`At most ${menus.name_max} characters.`}
      >
        {(p) => (
          <input
            name="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={menus.name_max * 2}
            {...p}
          />
        )}
      </DialogField>
      <DialogField
        id={`${id}-purpose`}
        label="What it is for"
        error={state.fieldErrors.purpose}
        hint="One sentence that tells staff when to use it."
      >
        {(p) => (
          <input
            name="purpose"
            value={purpose}
            onChange={(e) => setPurpose(e.target.value)}
            {...p}
          />
        )}
      </DialogField>
      <DialogField
        id={`${id}-instruction`}
        label="Instruction"
        error={state.fieldErrors.instruction}
        hint={`Tell the agent what to look for and when to suggest something, in plain words (at most ${menus.instruction_max} characters). Links are removed and words that try to change the AI's safety rules are refused. The agent can never do more than suggest.`}
      >
        {(p) => (
          <textarea
            name="instruction"
            rows={8}
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            {...p}
          />
        )}
      </DialogField>

      <fieldset className="space-y-3">
        <legend className="text-sm font-medium text-slate-700">
          What it may read{" "}
          <span className="font-normal text-slate-500">
            (choose up to {menus.max_read_sets}, all about the same kind of
            record)
          </span>
        </legend>
        {state.fieldErrors.read_sets && (
          <p role="alert" className="text-sm text-red-700">
            {state.fieldErrors.read_sets}
          </p>
        )}
        {GROUPS.map((group) => {
          const items = menus.read_sets.filter(
            (item) => item.record_type === group.type,
          );
          if (items.length === 0) return null;
          return (
            <div key={group.type}>
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                {group.heading}
              </p>
              <div className="mt-1 space-y-1">
                {items.map((item) => (
                  <label
                    key={item.key}
                    className="flex items-start gap-2 text-sm text-slate-800"
                  >
                    <input
                      type="checkbox"
                      name="read_sets"
                      value={item.key}
                      // After a refused save React resets the form; remounting the box on
                      // every attempt with the remembered choice as its default keeps it.
                      key={`${item.key}-${state.attempt}`}
                      defaultChecked={readSets.includes(item.key)}
                      onChange={() => setReadSets(toggle(readSets, item.key))}
                      className="mt-1"
                    />
                    <span>{item.description}</span>
                  </label>
                ))}
              </div>
            </div>
          );
        })}
        {type && (
          <p className="text-xs text-slate-500">
            This agent works on {recordNoun(type)}.
          </p>
        )}
      </fieldset>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium text-slate-700">
          What it may suggest{" "}
          <span className="font-normal text-slate-500">
            (choose up to {menus.max_suggestion_kinds})
          </span>
        </legend>
        {state.fieldErrors.suggestion_kinds && (
          <p role="alert" className="text-sm text-red-700">
            {state.fieldErrors.suggestion_kinds}
          </p>
        )}
        {menus.suggestion_kinds.map((item) => {
          const allowed = kindAllowed(item.key, type);
          return (
            <label
              key={item.key}
              className="flex items-start gap-2 text-sm text-slate-800"
            >
              <input
                type="checkbox"
                name="suggestion_kinds"
                value={item.key}
                key={`${item.key}-${state.attempt}`}
                defaultChecked={kinds.includes(item.key)}
                disabled={!allowed && !kinds.includes(item.key)}
                onChange={() => setKinds(toggle(kinds, item.key))}
                className="mt-1"
              />
              <span>
                {item.description}
                {!allowed && (
                  <span className="text-slate-500">
                    {" "}
                    (needs an agent that reads a lead)
                  </span>
                )}
              </span>
            </label>
          );
        })}
        <p className="text-xs text-slate-500">
          Every suggestion waits for a different person to approve it. An agent
          can never approve, delete, convert a lead, assign, send e-mail or
          change money.
        </p>
      </fieldset>

      <button
        type="submit"
        disabled={pending}
        className={buttonClass("primary")}
      >
        {pending ? "Saving…" : submitLabel}
      </button>
    </form>
  );
}
