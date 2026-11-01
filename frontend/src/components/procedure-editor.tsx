"use client";

import { useActionState, useId, useState } from "react";

import { DialogField } from "@/components/action-dialog";
import { AssessmentBody } from "@/components/qualifier-views";
import { ErrorAlert, buttonClass } from "@/components/ui";
import type { QualifierTrial } from "@/lib/api-types";
import type { DialogState } from "@/lib/dialog-state";
import { parseSteps } from "@/lib/qualifier";

type SaveState = DialogState & { values: Record<string, string> };
type TrialState = DialogState & {
  trial: QualifierTrial | null;
  values: Record<string, string>;
};

export type LeadChoice = { id: string; label: string };

/**
 * Writes the qualification procedure (administrators) and tries it on a lead. One step per line;
 * the numbers are added when it is shown. "Try it" shows what the Qualifier would conclude and
 * what it would propose - and changes nothing in the CRM. It can use the text above as a draft,
 * so a step can be tested before it is saved. Every check is done again by the API.
 */
export function ProcedureEditor({
  initialName,
  initialSteps,
  leads,
  saveInitial,
  tryInitial,
  saveAction,
  tryAction,
}: {
  initialName: string;
  initialSteps: string;
  leads: LeadChoice[];
  saveInitial: SaveState;
  tryInitial: TrialState;
  saveAction: (state: SaveState, formData: FormData) => Promise<SaveState>;
  tryAction: (state: TrialState, formData: FormData) => Promise<TrialState>;
}) {
  const id = useId();
  const [save, saveForm, saving] = useActionState(saveAction, saveInitial);
  const [trial, tryForm, trying] = useActionState(tryAction, tryInitial);
  const [name, setName] = useState(save.values.name ?? initialName);
  const [steps, setSteps] = useState(save.values.steps ?? initialSteps);
  const count = parseSteps(steps).length;

  return (
    <div className="space-y-8">
      <form action={saveForm} noValidate className="space-y-4">
        {save.error && (
          <ErrorAlert
            title="The procedure could not be saved"
            error={save.error}
          />
        )}
        <DialogField
          id={`${id}-name`}
          label="Name"
          error={save.fieldErrors.name}
        >
          {(p) => (
            <input
              name="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={100}
              {...p}
            />
          )}
        </DialogField>
        <DialogField
          id={`${id}-steps`}
          label="Steps"
          error={save.fieldErrors.steps}
          hint="One step per line, in plain words, for example “The budget is at least 80 lakh.” Links and instructions to an AI are not allowed."
        >
          {(p) => (
            <textarea
              name="steps"
              rows={8}
              value={steps}
              onChange={(e) => setSteps(e.target.value)}
              {...p}
            />
          )}
        </DialogField>
        <p className="text-xs text-slate-500">
          {count} {count === 1 ? "step" : "steps"} (at most 20). Saving makes a
          new version; the old one is kept.
        </p>
        <button
          type="submit"
          disabled={saving}
          className={buttonClass("primary")}
        >
          {saving ? "Saving…" : "Save as a new version"}
        </button>
      </form>

      <form
        action={tryForm}
        noValidate
        aria-label="Try the procedure"
        className="space-y-4 border-t border-slate-100 pt-6"
      >
        <h3 className="text-sm font-semibold text-slate-900">Try it</h3>
        <p className="text-sm text-slate-600">
          See what the Qualifier would conclude about one lead. Nothing is
          proposed or saved; the model call counts against the monthly token
          budget.
        </p>
        {trial.error && (
          <ErrorAlert title="The trial did not work" error={trial.error} />
        )}
        <DialogField
          id={`${id}-lead`}
          label="Lead"
          error={trial.fieldErrors.lead_id}
        >
          {(p) => (
            <select
              name="lead_id"
              defaultValue={trial.values.lead_id ?? ""}
              {...p}
            >
              <option value="">Choose a lead…</option>
              {leads.map((lead) => (
                <option key={lead.id} value={lead.id}>
                  {lead.label}
                </option>
              ))}
            </select>
          )}
        </DialogField>
        <label className="flex items-center gap-2 text-sm text-slate-800">
          <input
            type="checkbox"
            name="use_draft"
            defaultChecked={trial.values.use_draft === "on"}
          />
          Use the steps above as a draft (even if not saved)
        </label>
        <input type="hidden" name="draft_steps" value={steps} />
        <button
          type="submit"
          disabled={trying}
          className={buttonClass("secondary")}
        >
          {trying ? "Trying…" : "Try it"}
        </button>
        {trial.trial && <TrialResult trial={trial.trial} />}
      </form>
    </div>
  );
}

export function TrialResult({ trial }: { trial: QualifierTrial }) {
  return (
    <div
      role="status"
      className="rounded-md border border-slate-200 bg-slate-50 p-4"
    >
      <AssessmentBody item={trial} />
      <p className="mt-3 text-sm text-slate-700">
        {trial.would_propose
          ? `It would propose: ${trial.would_propose}`
          : "It would not propose anything."}
      </p>
      <p className="mt-1 text-xs text-slate-500">
        {trial.procedure_version === null
          ? "Tried with the draft above."
          : `Tried with saved version ${trial.procedure_version}.`}
      </p>
    </div>
  );
}
