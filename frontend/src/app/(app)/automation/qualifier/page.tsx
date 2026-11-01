import type { Metadata } from "next";

import { DeactivateProcedure } from "@/components/deactivate-procedure";
import {
  ProcedureEditor,
  type LeadChoice,
} from "@/components/procedure-editor";
import { Card, Forbidden, PageHeader, SuccessAlert } from "@/components/ui";
import type {
  LeadPage,
  QualificationProcedure,
  QualificationProcedurePage,
} from "@/lib/api-types";
import { formatDateTime } from "@/lib/format";
import { canManageQualifier, canReadQualifier } from "@/lib/permissions";
import { stepsToText } from "@/lib/qualifier";
import { initialSaveState, initialTrialState } from "@/lib/qualifier-state";
import { apiFetch, getMe } from "@/lib/server/api";

import {
  deactivateProcedure,
  saveProcedure,
  tryProcedure,
} from "../../qualifier/actions";

export const metadata: Metadata = { title: "Qualifier" };

const DONE: Record<string, string> = {
  saved: "The procedure was saved as a new version.",
  off: "The procedure was switched off. The Qualifier does nothing until a new one is saved.",
};

/**
 * The Qualifier's written procedure (docs/qualifier.md): the steps the organisation uses to
 * decide when a lead is qualified. Tenant admins write it and try it on a lead; sales managers
 * read it. The Qualifier only ever suggests - a different person approves every proposal.
 */
export default async function QualifierPage({
  searchParams,
}: PageProps<"/automation/qualifier">) {
  const query = await searchParams;
  const me = await getMe();
  if (!canReadQualifier(me)) return <Forbidden />;
  const canWrite = canManageQualifier(me);
  const [active, versions, leads] = await Promise.all([
    apiFetch<QualificationProcedure>("/qualifier/procedure").catch(() => null),
    apiFetch<QualificationProcedurePage>(
      "/qualifier/procedure/versions?limit=20",
    ),
    canWrite
      ? apiFetch<LeadPage>("/leads?limit=50")
          .then((page) => page.items)
          .catch(() => [])
      : Promise.resolve([]),
  ]);
  const done = typeof query.done === "string" ? DONE[query.done] : undefined;
  const choices: LeadChoice[] = leads.map((lead) => ({
    id: lead.id,
    label: [
      [lead.first_name, lead.last_name].filter(Boolean).join(" "),
      lead.company_name,
    ]
      .filter(Boolean)
      .join(" - "),
  }));

  return (
    <>
      {done && (
        <div className="mb-4">
          <SuccessAlert>{done}</SuccessAlert>
        </div>
      )}
      <PageHeader
        title="Qualifier"
        description="The steps your organisation uses to decide when a lead is qualified. The Qualifier reads one lead and these steps and suggests what to do. It never changes a lead itself: a different person approves every suggestion."
      />
      <div className="space-y-6">
        <Card className="p-5" aria-labelledby="current-heading">
          <h2
            id="current-heading"
            className="text-base font-semibold text-slate-900"
          >
            Current procedure
          </h2>
          {active ? (
            <>
              <p className="mt-1 text-sm text-slate-600">
                {active.name} · version {active.version} · saved{" "}
                <time dateTime={active.created_at}>
                  {formatDateTime(active.created_at)}
                </time>
              </p>
              <ol className="mt-3 list-decimal space-y-1 pl-5 text-sm text-slate-800">
                {active.steps.map((step, index) => (
                  <li key={index} className="break-words">
                    {step}
                  </li>
                ))}
              </ol>
              {active.cleaned.length > 0 && (
                <p className="mt-3 text-xs text-slate-500">
                  Some text was taken out when this was saved (
                  {active.cleaned.join(", ").replaceAll("_", " ")}).
                </p>
              )}
              {canWrite && (
                <div className="mt-4 border-t border-slate-100 pt-4">
                  <DeactivateProcedure
                    action={deactivateProcedure.bind(null, active.version)}
                  />
                </div>
              )}
            </>
          ) : (
            <p className="mt-2 text-sm text-slate-600">
              No procedure has been written yet, so the Qualifier does nothing.
            </p>
          )}
        </Card>

        {canWrite ? (
          <Card className="p-5" aria-labelledby="write-heading">
            <h2
              id="write-heading"
              className="text-base font-semibold text-slate-900"
            >
              {active ? "Write a new version" : "Write the procedure"}
            </h2>
            <div className="mt-4">
              <ProcedureEditor
                initialName={active?.name ?? ""}
                initialSteps={active ? stepsToText(active.steps) : ""}
                leads={choices}
                saveInitial={initialSaveState}
                tryInitial={initialTrialState}
                saveAction={saveProcedure.bind(null, active?.version ?? null)}
                tryAction={tryProcedure}
              />
            </div>
          </Card>
        ) : (
          <p className="text-sm text-slate-600">
            Only a tenant administrator can write the procedure.
          </p>
        )}

        {versions.items.length > 1 && (
          <Card className="p-5" aria-labelledby="history-heading">
            <h2
              id="history-heading"
              className="text-base font-semibold text-slate-900"
            >
              Earlier versions
            </h2>
            <ul className="mt-3 space-y-1 text-sm text-slate-700">
              {versions.items
                .filter((v) => !v.active)
                .map((v) => (
                  <li key={v.id}>
                    Version {v.version} · {v.name} · {v.steps.length}{" "}
                    {v.steps.length === 1 ? "step" : "steps"} ·{" "}
                    <time dateTime={v.created_at}>
                      {formatDateTime(v.created_at)}
                    </time>
                  </li>
                ))}
            </ul>
          </Card>
        )}
      </div>
    </>
  );
}
