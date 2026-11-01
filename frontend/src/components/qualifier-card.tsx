import { qualifyLead } from "@/app/(app)/qualifier/actions";
import { QualifyButton } from "@/components/qualify-button";
import { AssessmentHistory } from "@/components/qualifier-views";
import { Card } from "@/components/ui";
import type { LeadAssessmentPage, Me } from "@/lib/api-types";
import { canRunQualifier } from "@/lib/permissions";
import { apiFetch } from "@/lib/server/api";

/**
 * The Qualifier on a lead page (docs/qualifier.md): the last assessments and a "Qualify" button.
 * Like the other extra cards it is information - the page works without it - and the API answers
 * 404 when the person may not read the lead, then the card is simply not shown.
 */
export async function QualifierCard({
  me,
  leadId,
}: {
  me: Pick<Me, "permissions">;
  leadId: string;
}) {
  if (!canRunQualifier(me)) return null;
  const page = await apiFetch<LeadAssessmentPage>(
    `/qualifier/assessments?lead_id=${leadId}&limit=5`,
  ).catch(() => null);
  if (!page) return null;
  return (
    <Card id="qualifier" aria-labelledby="qualifier-heading" className="p-5">
      <h2
        id="qualifier-heading"
        className="text-base font-semibold text-slate-900"
      >
        Qualifier
      </h2>
      <div className="mt-3">
        <AssessmentHistory items={page.items} />
      </div>
      {page.total > page.items.length && (
        <p className="mt-2 text-xs text-slate-500">
          Showing the latest {page.items.length} of {page.total}.
        </p>
      )}
      <div className="mt-4 border-t border-slate-100 pt-4">
        <QualifyButton action={qualifyLead.bind(null, leadId)} />
      </div>
    </Card>
  );
}
