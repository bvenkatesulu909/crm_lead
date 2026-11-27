import type { AgentAction } from "@/lib/api-types";

/**
 * Automatic follow-up messages (ADR 0036): the administrators' settings and the way a draft is
 * shown. The bounds repeat the API's (and the database's) own; the API decides again.
 */

export const FOLLOW_UP_KIND = "communication.send_follow_up";

/** The organisation's settings as the API returns them. */
export type FollowUpSettings = {
  enabled: boolean;
  monthly_cap: number;
  daily_cap: number;
  pending_cap: number;
  expiry_days: number;
  cooldown_days: number;
  template_id: string | null;
  template_name: string | null;
  rule: string;
  version: number;
};

export const NUMBER_FIELDS = [
  {
    name: "monthly_cap",
    label: "Follow-ups per lead per month",
    hint: "At most this many drafts for one lead in 30 days.",
    min: 1,
    max: 8,
  },
  {
    name: "daily_cap",
    label: "Drafts per day (whole organisation)",
    hint: "A speed limit for the day. Up to 100.",
    min: 1,
    max: 100,
  },
  {
    name: "pending_cap",
    label: "Drafts waiting per owner",
    hint: "Stops a pile-up: no new draft for an owner who already has this many waiting.",
    min: 1,
    max: 20,
  },
  {
    name: "expiry_days",
    label: "Days a draft waits for a decision",
    hint: "After this it expires and nothing is sent.",
    min: 1,
    max: 30,
  },
  {
    name: "cooldown_days",
    label: "Days between follow-ups to one lead",
    hint: "After a draft, the same lead gets no new one for this long.",
    min: 1,
    max: 60,
  },
] as const;

export type NumberName = (typeof NUMBER_FIELDS)[number]["name"];

export type SettingsInput = {
  enabled: boolean;
  template_id: string | null;
} & Record<NumberName, number>;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Read the form. Messages are plain words; the API checks everything again. */
export function checkSettings(
  raw: Record<string, string>,
):
  | { ok: true; value: SettingsInput }
  | { ok: false; errors: Record<string, string> } {
  const errors: Record<string, string> = {};
  const numbers: Partial<Record<NumberName, number>> = {};
  for (const field of NUMBER_FIELDS) {
    const text = (raw[field.name] ?? "").trim();
    const value = Number(text);
    if (!/^\d+$/.test(text) || value < field.min || value > field.max)
      errors[field.name] =
        `Enter a whole number from ${field.min} to ${field.max}.`;
    else numbers[field.name] = value;
  }
  const enabled = raw.enabled === "on";
  const template = (raw.template_id ?? "").trim();
  if (template && !UUID.test(template))
    errors.template_id = "Choose a template.";
  if (enabled && !template)
    errors.template_id = "Choose a template before switching follow-ups on.";
  if (Object.keys(errors).length > 0) return { ok: false, errors };
  return {
    ok: true,
    value: {
      enabled,
      template_id: template || null,
      ...(numbers as Record<NumberName, number>),
    },
  };
}

const SETTINGS_ERRORS: Record<string, string> = {
  version_conflict:
    "Someone else changed these settings. Reload the page and try again.",
  follow_up_settings_invalid:
    "Some of the settings are not valid. Check the template and the numbers.",
};

export function settingsErrorText(
  code: string | null | undefined,
  fallback?: string,
): string {
  return (
    (code && SETTINGS_ERRORS[code]) ||
    fallback ||
    "The settings could not be saved."
  );
}

/** The e-mail a follow-up draft would send (subject and text), or null for any other proposal. */
export function followUpDraft(
  action: Pick<AgentAction, "kind" | "payload">,
): { subject: string; body: string } | null {
  if (action.kind !== FOLLOW_UP_KIND) return null;
  const { subject, body } = action.payload;
  if (typeof subject !== "string" || typeof body !== "string") return null;
  return { subject, body };
}
