import Link from "next/link";

import {
  cancelActivity,
  completeActivity,
  createActivity,
  reopenActivity,
  type ActivityLink,
} from "@/app/(app)/tasks/actions";
import { ActivityButtons } from "@/components/activity-buttons";
import { ActivityComposer } from "@/components/activity-composer";
import { Card, cx } from "@/components/ui";
import type {
  CrmActivity,
  CrmActivityPage,
  DirectoryUser,
  Me,
} from "@/lib/api-types";
import { formatDateTime } from "@/lib/format";
import {
  canAssignActivities,
  canReadActivities,
  canWriteActivities,
  hasAny,
} from "@/lib/permissions";
import { KIND_LABELS, PRIORITY_LABELS, dueLabel } from "@/lib/pipeline";
import { apiFetch } from "@/lib/server/api";

const RECORD_PATHS = {
  lead: "leads",
  account: "accounts",
  contact: "contacts",
  opportunity: "opportunities",
} as const;

/** Display only: same rule as the API (own items, or all with write:all). */
export function mayChange(
  me: Me,
  a: CrmActivity,
  ownsRecord: boolean,
): boolean {
  return (
    hasAny(me, "activity:write:all") ||
    (hasAny(me, "activity:write:own") &&
      (a.assignee_id === me.user_id ||
        a.created_by_user_id === me.user_id ||
        ownsRecord))
  );
}

export function ActivityItem({
  activity: a,
  people,
  canChange,
  returnTo,
  showRecord = false,
}: {
  activity: CrmActivity;
  people: DirectoryUser[];
  canChange: boolean;
  returnTo: string;
  showRecord?: boolean;
}) {
  const name = (id: string | null) =>
    id
      ? (people.find((p) => p.id === id)?.display_name ?? "Former colleague")
      : "—";
  const when =
    a.status === "open"
      ? a.due_at
        ? `${dueLabel(a.due_at, new Date())} (${formatDateTime(a.due_at)})`
        : "No due date"
      : a.completed_at
        ? formatDateTime(a.completed_at)
        : "";
  return (
    <li className="flex flex-wrap items-start justify-between gap-3 px-5 py-3" data-testid="activity-item">
      <div className="min-w-0">
        <p className="text-sm">
          <span className="mr-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{KIND_LABELS[a.kind]}</span>
          <span className={cx("font-medium text-slate-900", a.status === "cancelled" && "line-through text-slate-500")}>{a.subject}</span>
          {a.overdue && <span className="ml-2 rounded-full bg-red-50 px-2 py-0.5 text-xs font-medium text-red-700">Overdue</span>}
          {a.status === "open" && a.priority === "high" && <span className="ml-2 rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800">{PRIORITY_LABELS.high} priority</span>}
          {a.status === "done" && <span className="ml-2 rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">Done</span>}
          {a.status === "cancelled" && <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">Cancelled</span>}
        </p>
        {a.body && <p className="mt-0.5 whitespace-pre-line text-sm text-slate-600">{a.body}</p>}
        {a.outcome && <p className="mt-0.5 text-sm text-slate-600">Outcome: {a.outcome}</p>}
        <p className="mt-1 text-xs text-slate-500">
          {when} · {name(a.assignee_id)}
          {a.reminder_at && a.status === "open" && ` · reminder ${formatDateTime(a.reminder_at)}`}
          {showRecord && a.related_type && a.related_id && (
            <>
              {" · "}
              <Link href={`/${RECORD_PATHS[a.related_type]}/${a.related_id}`} className="text-brand-700 hover:underline">
                Open {a.related_type}
              </Link>
            </>
          )}
        </p>
      </div>
      {canChange && (
        <ActivityButtons
          subject={a.subject}
          status={a.status}
          complete={completeActivity.bind(null, a.id, a.version, returnTo)}
          cancel={a.kind !== "note" ? cancelActivity.bind(null, a.id, a.version, returnTo) : undefined}
          reopen={a.kind !== "note" ? reopenActivity.bind(null, a.id, a.version, returnTo) : undefined}
        />
      )}
    </li>
  ); // prettier-ignore
}

/**
 * "Activities and follow-ups" card for a record page: plan a task or log an interaction,
 * and see everything done or planned for this record (newest first).
 */
export async function ActivityPanel({
  link,
  me,
  people,
  ownsRecord,
  planOnly = false,
}: {
  link: NonNullable<ActivityLink>;
  me: Me;
  people: DirectoryUser[];
  ownsRecord: boolean;
  planOnly?: boolean;
}) {
  if (!canReadActivities(me)) return null;
  const returnTo = `/${RECORD_PATHS[link.type]}/${link.id}`;
  const page = await apiFetch<CrmActivityPage>(
    `/activities?${link.type}_id=${link.id}&sort=-when&limit=50`,
  ).catch(() => null);
  const assignees = canAssignActivities(me)
    ? people
        .filter((p) => p.id !== me.user_id)
        .map((p) => ({ id: p.id, name: p.display_name }))
    : undefined;

  return (
    <Card>
      <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">{planOnly ? "Tasks and follow-ups" : "Activities and follow-ups"}</h2>
      {canWriteActivities(me) && (
        <div className="border-b border-slate-200 px-5 py-4">
          <ActivityComposer action={createActivity.bind(null, link, returnTo)} assignees={assignees} planOnly={planOnly} />
        </div>
      )}
      {page === null ? (
        <p className="px-5 py-6 text-sm text-slate-600">Activities could not be loaded.</p>
      ) : page.items.length === 0 ? (
        <p className="px-5 py-6 text-sm text-slate-600">Nothing planned or logged yet.</p>
      ) : (
        <ol className="divide-y divide-slate-100">
          {page.items.map((a) => (
            <ActivityItem key={a.id} activity={a} people={people} returnTo={returnTo} canChange={mayChange(me, a, ownsRecord)} />
          ))}
        </ol>
      )}
    </Card>
  ); // prettier-ignore
}
