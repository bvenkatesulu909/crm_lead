import type { Metadata } from "next";
import Link from "next/link";

import { CallNotesSettingsForm } from "@/components/call-notes-settings-form";
import { Card, Forbidden, PageHeader, SuccessAlert } from "@/components/ui";
import type { CallNotesSettings } from "@/lib/call-notes";
import { initialFormState } from "@/lib/form-state";
import { canManageCallNotes } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import { saveFrame } from "./actions";

export const metadata: Metadata = { title: "Call notes" };

/**
 * Call notes and the deal checklist (ADR 0035): which frame the organisation uses, BANT or MEDDIC.
 * Tenant administrators only (the API checks again). Switching the feature on or off is done on the
 * AI agents page, like every other AI feature.
 */
export default async function CallNotesSettingsPage({
  searchParams,
}: PageProps<"/automation/call-notes">) {
  const query = await searchParams;
  const me = await getMe();
  if (!canManageCallNotes(me)) return <Forbidden />;
  const settings = await apiFetch<CallNotesSettings>("/call-notes/settings");

  return (
    <>
      {query.done === "saved" && (
        <div className="mb-4">
          <SuccessAlert>The checklist frame was saved.</SuccessAlert>
        </div>
      )}
      <PageHeader
        title="Call notes"
        description="After a recorded call has a transcript, a rep can ask for call notes and a deal checklist. Every line says whether the buyer stated it, it is only assumed, or it is unknown, with the words and the moment in the call. Choose the checklist your team uses."
      />
      <Card className="max-w-2xl p-5">
        <CallNotesSettingsForm
          settings={settings}
          initialState={initialFormState}
          action={saveFrame.bind(null, settings.version)}
        />
        <p className="mt-5 border-t border-slate-100 pt-4 text-sm text-slate-600">
          Call notes are off until you switch them on under{" "}
          <Link
            href="/automation/agents"
            className="font-medium text-brand-700 underline"
          >
            AI agents
          </Link>
          . They never change a lead by themselves: anything suggested for the
          buyer memory waits in the approval queue for a different person.
        </p>
      </Card>
    </>
  );
}
