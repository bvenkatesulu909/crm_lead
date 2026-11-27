import type { Metadata } from "next";
import Link from "next/link";

import { FollowUpSettingsForm } from "@/components/follow-up-settings-form";
import { Card, Forbidden, PageHeader, SuccessAlert } from "@/components/ui";
import type { EmailTemplate } from "@/lib/api-types";
import type { FollowUpSettings } from "@/lib/follow-ups";
import { initialFormState } from "@/lib/form-state";
import { canManageFollowUps } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import { saveFollowUpSettings } from "./actions";

export const metadata: Metadata = { title: "Follow-ups" };

/**
 * Automatic follow-up drafts (ADR 0036). Tenant administrators only (the API checks again).
 * One rule exists: a lead whose follow-up task is due today gets a draft e-mail, which waits in
 * the approval queue for the lead's owner or a manager.
 */
export default async function FollowUpSettingsPage({
  searchParams,
}: PageProps<"/automation/follow-ups">) {
  const query = await searchParams;
  const me = await getMe();
  if (!canManageFollowUps(me)) return <Forbidden />;
  const [settings, templates] = await Promise.all([
    apiFetch<FollowUpSettings>("/communications/follow-up-settings"),
    apiFetch<EmailTemplate[]>("/communications/templates"),
  ]);

  return (
    <>
      {query.done === "saved" && (
        <div className="mb-4">
          <SuccessAlert>The follow-up settings were saved.</SuccessAlert>
        </div>
      )}
      <PageHeader
        title="Follow-ups"
        description="When a lead's follow-up task is due today, the CRM can draft an e-mail for it. The draft waits for the lead's owner or a manager to read, reword and approve; only then is it sent. A lead who withdrew consent, a closed lead and a lead who already replied never get a draft."
      />
      <Card className="max-w-2xl p-5">
        <FollowUpSettingsForm
          settings={settings}
          templates={templates}
          initialState={initialFormState}
          action={saveFollowUpSettings.bind(null, settings.version)}
        />
        <p className="mt-5 border-t border-slate-100 pt-4 text-sm text-slate-600">
          Waiting drafts are on the{" "}
          <Link
            href="/approvals"
            className="font-medium text-brand-700 underline"
          >
            Approvals
          </Link>{" "}
          page. Switch every automatic follow-up off at once by turning this
          off.
        </p>
      </Card>
    </>
  );
}
