import type { Metadata } from "next";
import Link from "next/link";

import { MonthCalendar } from "@/components/task-views";
import {
  ButtonLink,
  Card,
  ErrorAlert,
  Forbidden,
  PageHeader,
  buttonClass,
  cx,
} from "@/components/ui";
import { ApiError, toErrorInfo } from "@/lib/api-error";
import type { CrmActivityPage } from "@/lib/api-types";
import { hasAny } from "@/lib/permissions";
import { monthParam, parseMonth } from "@/lib/pipeline";
import { apiFetch, getMe } from "@/lib/server/api";

export const metadata: Metadata = { title: "Calendar" };

const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

export default async function CalendarPage({
  searchParams,
}: PageProps<"/tasks/calendar">) {
  const query = await searchParams;
  const me = await getMe();
  const [year, month] = parseMonth(
    typeof query.month === "string" ? query.month : undefined,
    new Date(),
  );
  const everyone = hasAny(me, "activity:read:all") && query.scope === "all";
  // Load two days around the month: the browser shows days in its own time zone.
  const from = new Date(
    Date.UTC(year, month, 1) - 2 * 86_400_000,
  ).toISOString();
  const to = new Date(
    Date.UTC(year, month + 1, 1) + 2 * 86_400_000,
  ).toISOString();
  const params = new URLSearchParams({
    due_from: from,
    due_to: to,
    limit: "500",
    sort: "due_at",
  });
  if (!everyone) params.set("mine", "true");

  let page: CrmActivityPage;
  try {
    page = await apiFetch<CrmActivityPage>(`/activities?${params}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) return <Forbidden />;
    return (
      <ErrorAlert
        title="The calendar could not be loaded"
        error={toErrorInfo(error)}
      />
    );
  }
  const prev =
    month === 0 ? monthParam(year - 1, 11) : monthParam(year, month - 1);
  const next =
    month === 11 ? monthParam(year + 1, 0) : monthParam(year, month + 1);
  const scope = everyone ? "&scope=all" : "";

  return (
    <>
      <PageHeader
        title="Calendar"
        description="Tasks, calls and meetings by due date, in your local time."
        actions={<ButtonLink href="/tasks" variant="secondary">Task list</ButtonLink>}
      />
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-5 py-3">
          <div className="flex items-center gap-2">
            <Link href={`/tasks/calendar?month=${prev}${scope}`} className={buttonClass("secondary")} aria-label="Previous month">←</Link>
            <h2 className="min-w-40 text-center text-base font-semibold text-slate-900">{MONTHS[month]} {year}</h2>
            <Link href={`/tasks/calendar?month=${next}${scope}`} className={buttonClass("secondary")} aria-label="Next month">→</Link>
          </div>
          {hasAny(me, "activity:read:all") && (
            <div className="flex gap-2 text-sm">
              {([false, true] as const).map((all) => (
                <Link key={String(all)} href={`/tasks/calendar?month=${monthParam(year, month)}${all ? "&scope=all" : ""}`}
                  aria-current={everyone === all ? "page" : undefined}
                  className={cx("rounded-full px-3 py-1 font-medium ring-1 ring-inset", everyone === all ? "bg-brand-600 text-white ring-brand-600" : "bg-white text-slate-700 ring-slate-300")}>
                  {all ? "Everyone" : "Mine"}
                </Link>
              ))}
            </div>
          )}
        </div>
        <MonthCalendar year={year} month={month} items={page.items} />
      </Card>
    </>
  ); // prettier-ignore
}
