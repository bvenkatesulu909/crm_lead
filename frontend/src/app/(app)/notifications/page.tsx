import type { Metadata } from "next";
import Link from "next/link";

import {
  Card,
  EmptyState,
  Forbidden,
  PageHeader,
  buttonClass,
  cx,
} from "@/components/ui";
import type { NotificationPage } from "@/lib/api-types";
import { formatDateTime } from "@/lib/format";
import { canReadNotifications } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import { markAllRead, openNotification } from "./actions";

export const metadata: Metadata = { title: "Notifications" };

/** The signed-in person's notifications, newest first (the API only returns their own). */
export default async function NotificationsPage() {
  const me = await getMe();
  if (!canReadNotifications(me)) return <Forbidden />;
  const page = await apiFetch<NotificationPage>("/notifications?limit=100");
  return (
    <>
      <PageHeader
        title="Notifications"
        description={page.unread === 0 ? "You're all caught up." : `${page.unread} unread`}
        actions={<>
          <Link href="/notifications/settings" className={buttonClass("secondary")}>E-mail settings</Link>
          {page.unread > 0 && (
            <form action={markAllRead}><button type="submit" className={buttonClass("secondary")}>Mark all as read</button></form>
          )}
        </>}
      />
      <Card>
        {page.items.length === 0 ? (
          <EmptyState title="No notifications yet" description="You'll see assigned leads and tasks, reminders, quote approvals and customer answers here." />
        ) : (
          <ul aria-label="Notifications" className="divide-y divide-slate-100">
            {page.items.map((n) => (
              <li key={n.id}>
                <form action={openNotification.bind(null, n.id, n.link)}>
                  <button type="submit" className={cx("flex w-full items-start gap-3 px-5 py-3 text-left hover:bg-slate-50", !n.read_at && "bg-brand-50/40")}>
                    <span aria-hidden="true" className={cx("mt-1.5 size-2 shrink-0 rounded-full", n.read_at ? "bg-transparent" : "bg-brand-600")} />
                    <span className="min-w-0">
                      <span className={cx("block text-sm", n.read_at ? "text-slate-700" : "font-semibold text-slate-900")}>{n.title}</span>
                      <span className="block text-xs text-slate-500">{formatDateTime(n.created_at)}{!n.read_at && " · unread"}</span>
                    </span>
                  </button>
                </form>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  ); // prettier-ignore
}
