import type { Metadata } from "next";
import Link from "next/link";

import {
  Card,
  Forbidden,
  PageHeader,
  SuccessAlert,
  buttonClass,
} from "@/components/ui";
import type { NotificationPreference } from "@/lib/api-types";
import { canReadNotifications } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import { savePreferences } from "../actions";

export const metadata: Metadata = { title: "Notification settings" };

/** Which notifications also come by e-mail. Everything always appears in the CRM. */
export default async function NotificationSettingsPage({
  searchParams,
}: PageProps<"/notifications/settings">) {
  const query = await searchParams;
  const me = await getMe();
  if (!canReadNotifications(me)) return <Forbidden />;
  const prefs = await apiFetch<NotificationPreference[]>(
    "/notifications/preferences",
  );
  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link href="/notifications" className="font-medium text-brand-700 hover:underline">← Notifications</Link>
      </nav>
      {query.done === "saved" && <div className="mb-4"><SuccessAlert>Your e-mail settings were saved.</SuccessAlert></div>}
      <PageHeader title="Notification settings" description={`Everything appears under Notifications. Tick what should also be sent to ${me.email ?? "your e-mail address"}.`} />
      <Card className="p-6">
        <form action={savePreferences.bind(null, prefs.map((p) => p.type))} className="space-y-3">
          <fieldset>
            <legend className="mb-2 text-sm font-semibold text-slate-900">Also send an e-mail when…</legend>
            <ul className="space-y-2">
              {prefs.map((p) => (
                <li key={p.type}>
                  <label className="flex items-center gap-2 text-sm text-slate-700">
                    <input type="checkbox" name={`email:${p.type}`} defaultChecked={p.email} className="h-4 w-4 rounded border-slate-300 text-brand-600" />
                    {p.label}
                  </label>
                </li>
              ))}
            </ul>
          </fieldset>
          <button type="submit" className={buttonClass("primary")}>Save</button>
        </form>
      </Card>
    </>
  ); // prettier-ignore
}
