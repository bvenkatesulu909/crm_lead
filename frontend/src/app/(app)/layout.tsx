import { redirect } from "next/navigation";
import { connection } from "next/server";

import { AppShell } from "@/components/app-shell";
import { NotificationBell } from "@/components/notification-bell";
import { ReminderBell } from "@/components/reminder-bell";
import { ErrorAlert } from "@/components/ui";
import { UserMenu } from "@/components/user-menu";
import { ApiError, toErrorInfo } from "@/lib/api-error";
import type { Me, NotificationPage, Reminders } from "@/lib/api-types";
import { sidebarModulesFor } from "@/lib/modules";
import {
  canReadActivities,
  canReadNotifications,
  navigationFor,
} from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

/** Everything behind login. Loads the signed-in user once and builds the role-based shell. */
export default async function AuthenticatedLayout({
  children,
}: LayoutProps<"/">) {
  // Per-user pages: render on each request, never at build time (the build has no API/session).
  await connection();
  let me: Me;
  try {
    me = await getMe();
  } catch (error) {
    // Signed up but not approved yet: no CRM data, only the waiting page.
    if (
      error instanceof ApiError &&
      (error.problem.code === "access_pending" ||
        error.problem.code === "account_disabled")
    )
      redirect("/pending");
    return (
      <main className="mx-auto max-w-xl p-6">
        <ErrorAlert
          title="We couldn't load your account"
          error={toErrorInfo(error)}
        />
      </main>
    );
  }

  const name = me.display_name ?? me.email ?? "Signed-in user";
  const userMenu = (
    <UserMenu
      name={name}
      email={me.email}
      roles={me.roles}
      permissions={me.permissions}
    />
  );

  // Customers have their own portal; the staff CRM is only for employees.
  if (me.user_type === "customer") redirect("/portal");

  // The bell is a convenience: if reminders can't be loaded the page still works.
  const [reminders, notifications] = await Promise.all([
    canReadActivities(me)
      ? apiFetch<Reminders>("/activities/reminders").catch(() => null)
      : null,
    canReadNotifications(me)
      ? apiFetch<NotificationPage>("/notifications?limit=1").catch(() => null)
      : null,
  ]);

  const nav = navigationFor(me);
  return (
    <AppShell
      nav={nav}
      modules={sidebarModulesFor(
        me,
        nav.map((item) => item.href),
      )}
      userMenu={userMenu}
      headerActions={
        <>
          {notifications && <NotificationBell unread={notifications.unread} />}
          {reminders && <ReminderBell count={reminders.attention} />}
        </>
      }
    >
      {children}
    </AppShell>
  );
}
