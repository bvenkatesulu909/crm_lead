import type { Lead } from "@/lib/api-types";

const dateFormat = new Intl.DateTimeFormat("en-GB", { dateStyle: "medium" });

export function formatDate(iso: string): string {
  return dateFormat.format(new Date(iso));
}

export function leadName(lead: Pick<Lead, "first_name" | "last_name">): string {
  return [lead.first_name, lead.last_name].filter(Boolean).join(" ");
}

export const SOURCE_LABELS: Record<string, string> = {
  web: "Website",
  referral: "Referral",
  event: "Event",
  cold_call: "Cold call",
  partner: "Partner",
  advertisement: "Advertisement",
  other: "Other",
};

const dateTimeFormat = new Intl.DateTimeFormat("en-GB", {
  dateStyle: "medium",
  timeStyle: "short",
});

export function formatDateTime(iso: string): string {
  return dateTimeFormat.format(new Date(iso));
}

/** 1536 -> "1.5 KB" (file sizes). */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
