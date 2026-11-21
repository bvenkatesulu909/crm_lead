/**
 * Call notes and the deal checklist on a call recording (ADR 0035): the shapes the API returns and
 * the words shared by the panel and its Server Actions. The API decides everything that matters
 * (who may read the lead, the switch, the limits, whether a quote is really in the transcript);
 * these helpers only explain a refusal in plain words and save a round trip.
 */

export type LineState = "stated" | "assumed" | "unknown";

export type NotesLine = {
  position: number;
  field: string;
  label: string;
  state: LineState;
  value: string | null;
  quote: string | null;
  start_ms: number | null;
  end_ms: number | null;
  reason: string | null;
  /** Why a claim was turned into "unknown" (for example quote_not_found), if it was. */
  note_code: string | null;
};

export type NotesDraft = {
  id: string;
  version_no: number;
  framework: string;
  requested_by_user_id: string;
  model_name: string;
  downgraded: number;
  dropped_notes: number;
  cleaned_codes: string[];
  created_at: string;
  lines: NotesLine[];
};

export type NotesVersion = {
  version_no: number;
  framework: string;
  requested_by_user_id: string;
  created_at: string;
};

export type NotesPage = { newest: NotesDraft | null; versions: NotesVersion[] };

export type PlannedMemory = {
  position: number;
  field: string;
  label: string;
  key: string;
  value: string;
  note: string;
};

export type ProposalPreview = {
  memory: PlannedMemory[];
  task: { subject: string; due_in_days: number } | null;
};

export type ProposalOutcome = {
  target: string;
  position: number | null;
  status: "proposed" | "blocked" | "refused" | "skipped";
  proposal_id: string | null;
  proposal_link: string | null;
  message: string | null;
};

export type CallNotesSettings = {
  framework: string;
  version: number;
  frameworks: {
    key: string;
    title: string;
    fields: { key: string; label: string; hint: string }[];
  }[];
};

export const FRAMEWORK_KEYS = ["bant", "meddic"] as const;

export const STATE_LABELS: Record<LineState, string> = {
  stated: "Stated",
  assumed: "Assumed",
  unknown: "Unknown",
};

/** What each state means, shown under the draft so nobody has to guess. */
export const STATE_MEANINGS: Record<LineState, string> = {
  stated:
    "Words on the call give this answer (the quote is shown). The speaker is not identified.",
  assumed: "The call only hints at it. The reason is shown.",
  unknown: "Nothing on the call answers it.",
};

/** 6000 -> "0:06"; 3725000 -> "62:05". Minutes are not rolled into hours: it is a position in a call. */
export function stamp(milliseconds: number | null): string {
  if (milliseconds === null || !Number.isFinite(milliseconds)) return "";
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

/** Why a line is "unknown" although the AI answered it - in plain words. */
export function noteCodeText(code: string | null): string | null {
  switch (code) {
    case null:
      return null;
    case "quote_not_found":
      return "The AI quoted words that are not in the transcript, so this is shown as unknown.";
    case "value_not_in_quote":
      return "The value was not part of the words quoted, so this is shown as unknown.";
    case "quote_too_short":
      return "The quote was too short to prove anything, so this is shown as unknown.";
    case "bad_time":
      return "The moment named for the quote was not usable, so this is shown as unknown.";
    default:
      return "This answer could not be checked, so it is shown as unknown.";
  }
}

/** What was cleaned out of the text, as one sentence per kind of finding (never the text). */
export function cleanedText(codes: readonly string[]): string[] {
  const out: string[] = [];
  for (const code of codes) {
    if (code === "link") out.push("A link was removed.");
    else if (code === "instruction_phrase")
      out.push(
        "Some words read like instructions to an AI. They were treated only as words somebody said.",
      );
    else if (code === "email_address")
      out.push("An e-mail address was removed.");
    else if (code === "hidden_characters" || code === "control_characters")
      out.push("Hidden characters were removed.");
    else if (code === "html_markup" || code === "external_image")
      out.push("Markup or an image was removed.");
    else if (code === "repeated_text") out.push("Repeated text was removed.");
  }
  return out;
}

/** Plain words for the API's refusals. */
export function notesErrorText(code: string | null, fallback: string): string {
  switch (code) {
    case "agent_unavailable":
      return "Call notes are switched off for your organisation. An administrator can switch them on under AI agents.";
    case "agent_budget_reached":
      return "This month's AI budget for call notes is used up. Ask your administrator.";
    case "call_notes_rate_limited":
      return "Call notes were asked for too often just now. Try again later.";
    case "call_notes_transcript_too_long":
      return "The transcript is too long to read in one go.";
    case "call_notes_no_transcript":
      return "The recording has no transcript to read.";
    case "call_transcript_not_ready":
      return "The transcript is not ready yet.";
    case "call_notes_bad_answer":
    case "call_notes_unverified_answer":
      return "The AI's answer could not be checked against the transcript, so nothing was saved. Try again.";
    case "call_notes_not_found":
      return "Those call notes were not found.";
    case "call_notes_not_proposable":
      return "One of the chosen lines cannot be suggested to the buyer memory.";
    case "call_notes_duplicate_position":
    case "call_notes_too_many":
      return "Too many lines were chosen. Choose fewer and try again.";
    case "agent_action_limit_reached":
      return "Too many suggestions are waiting for a decision. Wait for them first.";
    case "call_notes_settings_conflict":
      return "Someone else changed this setting. Reload the page and try again.";
    case "call_not_found":
    case "lead_not_found":
      return "That recording was not found.";
    case "forbidden":
      return "You may not do this.";
    default:
      return fallback;
  }
}

/** One line per outcome of "suggest to the buyer memory". */
export function outcomeText(outcome: ProposalOutcome): string {
  switch (outcome.status) {
    case "proposed":
      return "Waiting for a different person to approve.";
    case "blocked":
      return `Not sent: ${outcome.message ?? "the safety check refused it."}`;
    case "refused":
      return `Not sent: ${outcome.message ?? "it cannot be suggested."}`;
    default:
      return "Not sent: too many suggestions are waiting for a decision.";
  }
}

/** Positions come from the browser: whole numbers from 1, at most 20, no repeats. */
export function checkPositions(
  positions: unknown,
): { ok: true; value: number[] | null } | { ok: false; message: string } {
  if (positions === null || positions === undefined)
    return { ok: true, value: null };
  if (!Array.isArray(positions) || positions.length > 20)
    return { ok: false, message: "Choose lines from the draft." };
  const whole = positions.every(
    (p) => typeof p === "number" && Number.isInteger(p) && p >= 1,
  );
  if (!whole || new Set(positions).size !== positions.length)
    return { ok: false, message: "Choose lines from the draft." };
  return { ok: true, value: positions as number[] };
}

export const isVersionNumber = (value: unknown): value is number =>
  typeof value === "number" && Number.isInteger(value) && value >= 1;

/** The frame choice from the settings form: only the two known frames. */
export function checkFramework(
  value: unknown,
): { ok: true; value: "bant" | "meddic" } | { ok: false; message: string } {
  return value === "bant" || value === "meddic"
    ? { ok: true, value }
    : { ok: false, message: "Choose BANT or MEDDIC." };
}
