import type { Metadata } from "next";
import Link from "next/link";

import {
  ButtonLink,
  Card,
  EmptyState,
  Forbidden,
  PageHeader,
  SuccessAlert,
  cx,
} from "@/components/ui";
import type {
  DirectoryUser,
  WorkflowCatalogue,
  WorkflowRule,
  WorkflowRun,
} from "@/lib/api-types";
import { formatDateTime } from "@/lib/format";
import { canManageWorkflows } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";
import { describeAction, describeCondition } from "@/lib/workflows";

export const metadata: Metadata = { title: "Automation" };

const DONE: Record<string, string> = {
  created: "The rule was created. It acts from now on.",
  saved: "The rule was saved.",
  deleted: "The rule was deleted.",
};
const RUN_STYLE = {
  done: "bg-emerald-50 text-emerald-800",
  failed: "bg-red-50 text-red-700",
  limited: "bg-amber-50 text-amber-800",
} as const;

/** Tenant admins: automation rules and what they did (run log). */
export default async function AutomationPage({
  searchParams,
}: PageProps<"/automation">) {
  const query = await searchParams;
  const me = await getMe();
  if (!canManageWorkflows(me)) return <Forbidden />;
  const [rules, runs, catalogue, people] = await Promise.all([
    apiFetch<WorkflowRule[]>("/workflows/rules"),
    apiFetch<WorkflowRun[]>("/workflows/runs?limit=50"),
    apiFetch<WorkflowCatalogue>("/workflows/catalogue"),
    apiFetch<DirectoryUser[]>("/users").catch(() => []),
  ]);
  const names = Object.fromEntries(people.map((p) => [p.id, p.display_name]));
  const triggerLabel = (key: string, days: number | null) => {
    const t = catalogue.triggers.find((x) => x.key === key);
    return t
      ? `${t.label}${t.kind === "schedule" ? ` (${t.days_label}: ${days ?? 0})` : ""}`
      : key;
  };
  const done = typeof query.done === "string" ? DONE[query.done] : undefined;

  return (
    <>
      {done && <div className="mb-4"><SuccessAlert>{done}</SuccessAlert></div>}
      <PageHeader title="Automation" description="Rules that react to what happens in the CRM - they create tasks, notify people or change a field for you."
        actions={<ButtonLink href="/automation/new">New rule</ButtonLink>} />
      <div className="grid gap-6 lg:grid-cols-5">
        <Card className="lg:col-span-3" aria-labelledby="rules-heading">
          <h2 id="rules-heading" className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">Rules</h2>
          {rules.length === 0 ? (
            <EmptyState title="No rules yet" description="For example: when a quote needs approval and the discount is more than 20 %, create a task for its owner." />
          ) : (
            <ul className="divide-y divide-slate-100">
              {rules.map((r) => (
                <li key={r.id} id={`rule-${r.id}`} className="px-5 py-4 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <Link href={`/automation/${r.id}`} className="font-medium text-brand-700 hover:underline">{r.name}</Link>
                    <span className={cx("rounded-full px-2 py-0.5 text-xs", r.is_active ? "bg-emerald-50 text-emerald-800" : "bg-slate-100 text-slate-600")}>{r.is_active ? "Active" : "Paused"}</span>
                  </div>
                  <p className="mt-1 text-slate-700"><span className="font-medium">When</span> {triggerLabel(r.trigger, r.days)}</p>
                  {r.conditions.map((c, i) => <p key={i} className="text-slate-700"><span className="font-medium">and</span> {describeCondition(c, catalogue, r.trigger)}</p>)}
                  {r.actions.map((a, i) => <p key={i} className="text-slate-700"><span className="font-medium">then</span> {describeAction(a, names)}</p>)}
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card className="self-start lg:col-span-2" aria-labelledby="runs-heading">
          <h2 id="runs-heading" className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">Recent runs</h2>
          {runs.length === 0 ? (
            <p className="px-5 py-4 text-sm text-slate-600">Nothing has happened yet.</p>
          ) : (
            <ul aria-label="Run log" className="divide-y divide-slate-100">
              {runs.map((run) => (
                <li key={run.id} className="px-5 py-3 text-sm">
                  <div className="flex items-start justify-between gap-2">
                    <span className="font-medium text-slate-900">{run.rule_name}</span>
                    <span className={cx("shrink-0 rounded-full px-2 py-0.5 text-xs", RUN_STYLE[run.status])}>{run.status === "done" ? "Done" : run.status === "failed" ? "Failed" : "Stopped"}</span>
                  </div>
                  <p className="text-slate-700">{run.record_label}</p>
                  {run.message && <p className="text-xs text-slate-600">{run.message}</p>}
                  <p className="text-xs text-slate-500">{formatDateTime(run.created_at)}</p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  ); // prettier-ignore
}
