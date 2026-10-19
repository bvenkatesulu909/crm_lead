import type { Metadata } from "next";
import Link from "next/link";
import { Fragment } from "react";

import { ActivityComposer } from "@/components/activity-composer";
import { ActivityItem, mayChange } from "@/components/activity-panel";
import { TaskGroups } from "@/components/task-views";
import {
  ButtonLink,
  Card,
  ErrorAlert,
  Forbidden,
  PageHeader,
  SuccessAlert,
  cx,
} from "@/components/ui";
import { ApiError, toErrorInfo } from "@/lib/api-error";
import type { CrmActivityPage, DirectoryUser } from "@/lib/api-types";
import {
  canAssignActivities,
  canWriteActivities,
  hasAny,
} from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import { createActivity } from "./actions";

export const metadata: Metadata = { title: "Tasks" };

const DONE: Record<string, string> = {
  planned: "The task was added.",
  logged: "The activity was logged.",
  completed: "Marked as done.",
  cancelled: "The task was cancelled.",
  reopened: "The task is open again.",
};

export default async function TasksPage({ searchParams }: PageProps<"/tasks">) {
  const query = await searchParams;
  const me = await getMe();
  const everyoneAllowed = hasAny(me, "activity:read:all");
  const everyone = everyoneAllowed && query.scope === "all";
  const scope = everyone ? "" : "&mine=true";

  let open: CrmActivityPage;
  let closed: CrmActivityPage;
  let people: DirectoryUser[];
  try {
    [open, closed, people] = await Promise.all([
      apiFetch<CrmActivityPage>(`/activities?status=open&sort=due_at&limit=500${scope}`),
      apiFetch<CrmActivityPage>(`/activities?status=done&status=cancelled&kind=task&kind=call&kind=meeting&kind=email&sort=-completed_at&limit=15${scope}`),
      apiFetch<DirectoryUser[]>("/users").catch(() => []),
    ]); // prettier-ignore
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) return <Forbidden />;
    return (
      <>
        <PageHeader title="Tasks" />
        <ErrorAlert
          title="Tasks could not be loaded"
          error={toErrorInfo(error)}
        />
      </>
    );
  }
  const done = typeof query.done === "string" ? DONE[query.done] : undefined;
  // Ownership of the linked record isn't known here; the API still allows those changes.
  const row = (a: CrmActivityPage["items"][number]) => (
    <ActivityItem
      activity={a}
      people={people}
      returnTo="/tasks"
      canChange={mayChange(me, a, false)}
      showRecord
    />
  );
  const tab = (all: boolean, label: string) => (
    <Link href={all ? "/tasks?scope=all" : "/tasks"} aria-current={everyone === all ? "page" : undefined}
      className={cx("rounded-full px-4 py-1.5 text-sm font-medium ring-1 ring-inset",
        everyone === all ? "bg-brand-600 text-white ring-brand-600" : "bg-white text-slate-700 ring-slate-300 hover:bg-slate-50")}>
      {label}
    </Link>
  ); // prettier-ignore

  return (
    <>
      <PageHeader
        title="Tasks"
        description="Your to-dos and planned follow-ups. The bell in the header counts what is overdue, due within 24 hours or past its reminder."
        actions={<ButtonLink href="/tasks/calendar" variant="secondary">Calendar</ButtonLink>}
      />
      {done && <div className="mb-4"><SuccessAlert>{done}</SuccessAlert></div>}
      {everyoneAllowed && (
        <nav aria-label="Whose tasks" className="mb-4 flex gap-2">
          {tab(false, "My tasks")}
          {tab(true, "Everyone")}
        </nav>
      )}
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <TaskGroups items={open.items} rendered={Object.fromEntries(open.items.map((a) => [a.id, row(a)]))} />
            {open.total > open.items.length && (
              <p className="border-t border-slate-100 px-5 py-2 text-xs text-slate-500">Showing the first {open.items.length} of {open.total} open items.</p>
            )}
          </Card>
          <Card>
            <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">Recently finished</h2>
            {closed.items.length === 0 ? (
              <p className="px-5 py-6 text-sm text-slate-600">Nothing finished yet.</p>
            ) : (
              <ol className="divide-y divide-slate-100">{closed.items.map((a) => <Fragment key={a.id}>{row(a)}</Fragment>)}</ol>
            )}
          </Card>
        </div>
        {canWriteActivities(me) && (
          <Card className="h-fit p-5">
            <h2 className="mb-4 text-base font-semibold text-slate-900">New task</h2>
            <ActivityComposer
              action={createActivity.bind(null, null, "/tasks")}
              assignees={canAssignActivities(me) ? people.filter((p) => p.id !== me.user_id).map((p) => ({ id: p.id, name: p.display_name })) : undefined}
            />
            <p className="mt-4 text-xs text-slate-500">
              To link a task to a customer, deal or lead, add it on that record&apos;s page. E-mail reminders come with the background worker (next phase); reminders show here and in the header.
            </p>
          </Card>
        )}
      </div>
    </>
  ); // prettier-ignore
}
