"use client";

import Link from "next/link";
import { Fragment, useEffect, useState, type ReactNode } from "react";

import { cx } from "@/components/ui";
import type { CrmActivity } from "@/lib/api-types";
import {
  KIND_LABELS,
  groupTasks,
  monthGrid,
  sameLocalDay,
} from "@/lib/pipeline";

/** The browser's "now", set after the page appears (the server doesn't know the user's
 *  time zone, so grouping by day happens here). Re-checked every minute. */
function useNow(): Date | null {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    const tick = () => setNow(new Date());
    tick();
    const timer = window.setInterval(tick, 60_000);
    return () => window.clearInterval(timer);
  }, []);
  return now;
}

const GROUPS = [
  ["overdue", "Overdue"],
  ["today", "Due today"],
  ["upcoming", "Upcoming"],
  ["someday", "No due date"],
] as const;

/**
 * Open tasks grouped by the user's local day. `rendered` holds the server-rendered row for
 * each task (with its Done/Cancel buttons); this component only decides where it goes.
 */
export function TaskGroups({
  items,
  rendered,
}: {
  items: CrmActivity[];
  rendered: Record<string, ReactNode>;
}) {
  const now = useNow();
  if (!now)
    return (
      <ol className="divide-y divide-slate-100">
        {items.map((a) => (
          <Fragment key={a.id}>{rendered[a.id]}</Fragment>
        ))}
      </ol>
    );
  const groups = groupTasks(items, now);
  return (
    <div className="divide-y divide-slate-200">
      {GROUPS.map(([key, title]) => (
        <section key={key} aria-labelledby={`group-${key}`}>
          <h2 id={`group-${key}`} className={cx("flex items-center gap-2 bg-slate-50 px-5 py-2 text-sm font-semibold", key === "overdue" && groups.overdue.length ? "text-red-700" : "text-slate-700")}>
            {title} <span className="rounded-full bg-white px-2 text-xs font-medium text-slate-600 ring-1 ring-slate-200">{groups[key].length}</span>
          </h2>
          {groups[key].length === 0 ? (
            <p className="px-5 py-3 text-sm text-slate-500">Nothing here.</p>
          ) : (
            <ol className="divide-y divide-slate-100">{groups[key].map((a) => <Fragment key={a.id}>{rendered[a.id]}</Fragment>)}</ol>
          )}
        </section>
      ))}
    </div>
  ); // prettier-ignore
}

const RECORD_PATHS = {
  lead: "leads",
  account: "accounts",
  contact: "contacts",
  opportunity: "opportunities",
} as const;

/** Month view of open and done items with a due date, in the user's local time. */
export function MonthCalendar({
  year,
  month,
  items,
}: {
  year: number;
  month: number;
  items: CrmActivity[];
}) {
  const now = useNow();
  if (!now)
    return (
      <p className="px-5 py-10 text-center text-sm text-slate-500">
        Loading calendar…
      </p>
    );
  const days = monthGrid(year, month);
  const weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[48rem] table-fixed border-collapse text-sm">
        <thead>
          <tr>{weekdays.map((d) => <th key={d} scope="col" className="border-b border-slate-200 py-2 text-xs font-semibold uppercase text-slate-500">{d}</th>)}</tr>
        </thead>
        <tbody>
          {Array.from({ length: days.length / 7 }, (_, week) => (
            <tr key={week}>
              {days.slice(week * 7, week * 7 + 7).map((day) => {
                const dayItems = items
                  .filter((a) => a.due_at && sameLocalDay(new Date(a.due_at), day))
                  .sort((a, b) => Date.parse(a.due_at ?? "") - Date.parse(b.due_at ?? ""));
                const outside = day.getMonth() !== month;
                const today = sameLocalDay(day, now);
                return (
                  <td key={day.toISOString()} className={cx("h-28 border border-slate-100 p-1 align-top", outside && "bg-slate-50")}>
                    <p className={cx("mb-1 text-right text-xs", today ? "font-bold text-brand-700" : outside ? "text-slate-400" : "text-slate-600")}>
                      {today ? <span className="rounded-full bg-brand-600 px-1.5 text-white">{day.getDate()}</span> : day.getDate()}
                    </p>
                    <ul className="space-y-1">
                      {dayItems.map((a) => (
                        <li key={a.id}>
                          <Link
                            href={a.related_type && a.related_id ? `/${RECORD_PATHS[a.related_type]}/${a.related_id}` : "/tasks"}
                            title={`${KIND_LABELS[a.kind]}: ${a.subject}`}
                            className={cx("block truncate rounded px-1.5 py-0.5 text-xs",
                              a.status !== "open" ? "bg-slate-100 text-slate-500 line-through"
                                : a.overdue ? "bg-red-50 text-red-800" : "bg-brand-50 text-brand-800")}
                          >
                            {new Date(a.due_at ?? "").toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} {a.subject}
                          </Link>
                        </li>
                      ))}
                    </ul>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ); // prettier-ignore
}
