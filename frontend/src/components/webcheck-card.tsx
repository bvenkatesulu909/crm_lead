import { requestWebCheck } from "@/app/(app)/webcheck/actions";
import { Card } from "@/components/ui";
import { WebCheckForm } from "@/components/webcheck-form";
import { WebEvidenceList } from "@/components/webcheck-views";
import type { Me, WebCheckSourcePage, WebEvidencePage } from "@/lib/api-types";
import { canReadWebCheck, canRunWebCheck } from "@/lib/permissions";
import { apiFetch } from "@/lib/server/api";
import type { WebCheckRecord } from "@/lib/webcheck";

/**
 * Web check of a lead or account (ADR 0019): look up a RERA number or a company on a public
 * registry; the result is kept as evidence. Like the other extra cards it is information - the
 * page works without it - and the API answers 404 when the person may not read the record,
 * then the card is simply not shown.
 */
export async function WebCheckCard({
  me,
  record,
}: {
  me: Pick<Me, "permissions">;
  record: WebCheckRecord;
}) {
  const mayRun = canRunWebCheck(me);
  const mayRead = canReadWebCheck(me);
  if (!mayRun && !mayRead) return null;
  const [evidence, sources] = await Promise.all([
    mayRead
      ? apiFetch<WebEvidencePage>(
          `/webcheck/evidence?target_type=${record.type}&target_id=${record.id}`,
        ).catch(() => null)
      : Promise.resolve({ items: [] } as WebEvidencePage),
    mayRun
      ? apiFetch<WebCheckSourcePage>("/webcheck/sources")
          .then((page) => page.items)
          .catch(() => [])
      : Promise.resolve([]),
  ]);
  if (!evidence) return null;
  const headingId = `webcheck-${record.id}`;
  return (
    <Card aria-labelledby={headingId} className="p-5">
      <h2 id={headingId} className="text-base font-semibold text-slate-900">
        Web check
      </h2>
      <p className="mt-1 text-sm text-slate-600">
        Look up a RERA number or a company on a public registry. The result
        appears here and you get a notification.
      </p>
      {mayRun && (
        <div className="mt-4">
          <WebCheckForm
            sources={sources}
            action={requestWebCheck.bind(null, record)}
          />
        </div>
      )}
      <div className="mt-4">
        <WebEvidenceList items={evidence.items} sources={sources} />
      </div>
    </Card>
  );
}
