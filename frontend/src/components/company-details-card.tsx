import {
  applyCompanyDetails,
  askCompanyDetails,
} from "@/app/(app)/webcheck/company-actions";
import {
  AskCompanyDetails,
  CompanySuggestions,
} from "@/components/company-details-views";
import { Card } from "@/components/ui";
import type { CompanyDetails, Me } from "@/lib/api-types";
import { canReadWebCheck, canRunWebCheck } from "@/lib/permissions";
import { apiFetch } from "@/lib/server/api";

/**
 * Company details on a lead (ADR 0026): ask for a look-up of the company's own website, see what
 * it suggests next to what the lead has, tick and save. Information only - the page works without
 * it - and the API answers 404 when the person may not read the lead, then nothing is shown.
 */
export async function CompanyDetailsCard({
  me,
  leadId,
}: {
  me: Pick<Me, "permissions">;
  leadId: string;
}) {
  const mayRun = canRunWebCheck(me);
  if (!mayRun && !canReadWebCheck(me)) return null;
  const details = await apiFetch<CompanyDetails>(
    `/webcheck/company-details?lead_id=${leadId}`,
  ).catch(() => null);
  if (!details) return null;
  return (
    <Card
      id="company-details"
      aria-labelledby="company-details-heading"
      className="p-5"
    >
      <h2
        id="company-details-heading"
        className="text-base font-semibold text-slate-900"
      >
        Company details
      </h2>
      <div className="mt-3">
        <CompanySuggestions
          details={details}
          canSave={mayRun}
          action={applyCompanyDetails.bind(null, leadId)}
        />
      </div>
      {mayRun && (
        <div className="mt-4 border-t border-slate-100 pt-4">
          <AskCompanyDetails action={askCompanyDetails.bind(null, leadId)} />
        </div>
      )}
    </Card>
  );
}
