"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import type { NotificationPreference } from "@/lib/api-types";
import { apiFetch } from "@/lib/server/api";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Only pages of this CRM ("/leads/…"), never another site ("//evil.example"). */
function safeLink(link: string): string {
  return /^\/(?!\/)[A-Za-z0-9/_\-]*$/.test(link) ? link : "/notifications";
}

/** Open a notification: mark it read (the API checks it is yours), then go to its page. */
export async function openNotification(id: string, link: string) {
  if (!UUID.test(id)) throw new Error("invalid notification");
  await apiFetch(`/notifications/${id}/read`, { method: "POST" }).catch(
    () => undefined,
  );
  revalidatePath("/", "layout"); // the unread badge in the header
  redirect(safeLink(link));
}

export async function markAllRead() {
  await apiFetch("/notifications/read-all", { method: "POST" });
  revalidatePath("/", "layout");
  redirect("/notifications");
}

/** Save which notifications also come by e-mail (unchecked boxes are not sent: "off"). */
export async function savePreferences(types: string[], formData: FormData) {
  await apiFetch<NotificationPreference[]>("/notifications/preferences", {
    method: "PUT",
    body: JSON.stringify({
      items: types.slice(0, 50).map((type) => ({
        type,
        email: formData.get(`email:${type}`) === "on",
      })),
    }),
  });
  redirect("/notifications/settings?done=saved");
}
