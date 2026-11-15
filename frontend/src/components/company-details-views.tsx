"use client";

import { useActionState, useId } from "react";

import { ErrorAlert, buttonClass } from "@/components/ui";
import type { CompanyDetails } from "@/lib/api-types";
import {
  companyRows,
  lookupErrorText,
  lookupVerdict,
} from "@/lib/company-details";
import { initialDialogState, type DialogState } from "@/lib/dialog-state";
import { cleanedNotes } from "@/lib/webcheck";

type AskAction = (state: DialogState) => Promise<DialogState>;
type ApplyAction = (
  state: DialogState,
  formData: FormData,
) => Promise<DialogState>;

/** "Find company details": asks for a look-up of the lead's own company website. Sends only the lead. */
export function AskCompanyDetails({ action }: { action: AskAction }) {
  const [state, formAction, pending] = useActionState(
    action,
    initialDialogState,
  );
  return (
    <form action={formAction} className="space-y-3">
      {state.error && (
        <ErrorAlert
          title="The look-up could not be asked for"
          error={state.error}
        />
      )}
      <button
        type="submit"
        disabled={pending}
        className={buttonClass("secondary")}
      >
        {pending ? "Asking…" : "Find company details"}
      </button>
      <p className="text-xs text-slate-500">
        Reads the home page of the lead&apos;s company website (or the domain of
        its work e-mail). Nothing about the person leaves the CRM, and nothing
        is saved until you choose.
      </p>
    </form>
  );
}

/**
 * The newest suggestions next to what the lead has now. Each row that differs can be ticked; only
 * the NAMES of the ticked fields go to the server, which takes the values from the stored
 * evidence. Everything a page said is shown as plain text.
 */
export function CompanySuggestions({
  details,
  action,
  canSave,
}: {
  details: CompanyDetails;
  action: ApplyAction;
  canSave: boolean;
}) {
  const [state, formAction, pending] = useActionState(
    action,
    initialDialogState,
  );
  const id = useId();
  const latest = details.latest;
  if (!latest)
    return (
      <p className="text-sm text-slate-600">
        No look-up yet. Press the button to read the company&apos;s website.
      </p>
    );
  const rows = companyRows(details);
  const anyApply = rows.some((r) => r.canApply);
  const notes = cleanedNotes(latest.cleaned);
  const failed = latest.verdict === "error" || latest.verdict === "unclear";
  return (
    <form action={formAction} className="space-y-3">
      <p className="text-sm font-medium text-slate-800">
        {lookupVerdict(latest.verdict)}
      </p>
      {failed && (
        <p className="text-sm text-slate-600">
          {lookupErrorText(latest.error_code)}
        </p>
      )}
      {!failed && (
        <>
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-slate-500">
              <tr>
                <th className="py-1 pr-2 font-medium">
                  <span className="sr-only">Save</span>
                </th>
                <th className="py-1 pr-2 font-medium">Field</th>
                <th className="py-1 pr-2 font-medium">Now</th>
                <th className="py-1 font-medium">Suggested</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.field} className="border-t border-slate-100">
                  <td className="py-1.5 pr-2">
                    {r.canApply && canSave && (
                      <input
                        type="checkbox"
                        name="field"
                        value={r.field}
                        id={`${id}-${r.field}`}
                        aria-label={`Save ${r.label}`}
                        defaultChecked
                      />
                    )}
                  </td>
                  <td className="py-1.5 pr-2 text-slate-600">{r.label}</td>
                  <td className="py-1.5 pr-2">{r.current ?? "—"}</td>
                  <td className="py-1.5">
                    {r.suggested ?? (
                      <span className="text-slate-400">nothing found</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {latest.excerpt && (
            <p className="text-xs whitespace-pre-line text-slate-600">
              {latest.excerpt}
            </p>
          )}
          {latest.pages.length > 0 && (
            <p className="text-xs text-slate-500">
              Read: {latest.pages.join(", ")}
            </p>
          )}
        </>
      )}
      {notes.length > 0 && (
        <p className="text-xs text-slate-500">
          Cleaned before it was shown: {notes.join("; ")}.
        </p>
      )}
      {state.error && (
        <ErrorAlert
          title="The details could not be saved"
          error={state.error}
        />
      )}
      {state.fieldErrors.field && (
        <p role="alert" className="text-sm text-red-700">
          {state.fieldErrors.field}
        </p>
      )}
      <input type="hidden" name="version" value={details.current.version} />
      <input type="hidden" name="evidence_id" value={latest.id} />
      {!failed && canSave && anyApply && (
        <button
          type="submit"
          disabled={pending}
          className={buttonClass("primary")}
        >
          {pending ? "Saving…" : "Save the ticked details"}
        </button>
      )}
      {!failed && !anyApply && (
        <p className="text-xs text-slate-500">
          The lead already has everything this look-up suggests.
        </p>
      )}
    </form>
  );
}
