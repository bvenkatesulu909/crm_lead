/**
 * Call recordings on the lead page (ADR 0030): the words and the checks shared by the card and its
 * Server Actions. The API decides everything that matters (the lead, the consent, the type, the size,
 * the limits); these checks only save a round trip and explain a refusal in plain words.
 */
import { isUuid } from "@/lib/communications";

export type CallLanguage = "hi" | "te" | "en";

export const CALL_LANGUAGES: { value: CallLanguage; label: string }[] = [
  { value: "hi", label: "Hindi (or Hindi and English mixed)" },
  { value: "te", label: "Telugu (or Telugu and English mixed)" },
  { value: "en", label: "English" },
];

export const languageLabel = (code: string) =>
  CALL_LANGUAGES.find((l) => l.value === code)?.label.split(" (")[0] ?? code;

/** One recording as the list shows it (no transcript text). */
export type CallRecording = {
  id: string;
  lead_id: string;
  language: string;
  status: string;
  failure_code: string | null;
  file_name: string;
  size_bytes: number | null;
  duration_seconds: number | null;
  consent_confirmed_at: string;
  created_at: string;
  finished_at: string | null;
  audio_available: boolean;
  audio_deleted_at: string | null;
  has_transcript: boolean;
  engine: string | null;
};

export type CallSegment = { start: number; end: number; text: string };

export type CallDetail = CallRecording & {
  transcript: string | null;
  segments: CallSegment[] | null;
};

export type CallListen = {
  url: string;
  expires_in_seconds: number;
  which: "original" | "cleaned";
};

export const MAX_FILE_BYTES = 100 * 1024 * 1024;
export const AUDIO_EXTENSIONS = [
  ".mp3",
  ".m4a",
  ".wav",
  ".ogg",
  ".webm",
  ".amr",
];
export const ACCEPT = AUDIO_EXTENSIONS.join(",");

/** Where a recording is in its life, in words. */
export function statusLabel(call: Pick<CallRecording, "status">): string {
  switch (call.status) {
    case "uploading":
      return "Upload not finished";
    case "queued":
    case "processing":
      return "Being cleaned and transcribed";
    case "ready":
      return "Transcript ready";
    case "failed":
      return "Could not be processed";
    case "expired":
      return "Upload expired";
    default:
      return "Unknown";
  }
}

/** Still waiting for the worker: the card refreshes itself while any recording is in this state. */
export const isWorking = (call: Pick<CallRecording, "status">) =>
  call.status === "queued" || call.status === "processing";

/** What a failure code means for the rep, and what to do about it. */
export function failureText(code: string | null): string {
  switch (code) {
    case "too_long":
      return "The recording is longer than the limit. Cut it into parts and add them one by one.";
    case "unreadable":
      return "The audio could not be read. The file may be damaged or cut off; export it again and add it again.";
    case "no_speech":
      return "No speech was found in the recording.";
    case "call_audio_off":
      return "Call recordings were switched off for your organisation before this one was processed.";
    case "budget_reached":
      return "This month's call minutes for your organisation are used up. Ask your administrator.";
    case "audio_deleted":
      return "The audio was deleted before it could be processed.";
    case "processing_failed":
      return "Processing did not work after several tries. Tell your administrator.";
    case "too_large":
      return "The file was larger than the size that was announced.";
    case "not_audio":
      return "The file is not the kind of audio its name says.";
    default:
      return "The recording could not be processed.";
  }
}

/** 3725 -> "1:02:05"; 65 -> "1:05"; null -> "". */
export function formatDuration(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds) || seconds < 0) return "";
  const whole = Math.floor(seconds);
  const h = Math.floor(whole / 3600);
  const m = Math.floor((whole % 3600) / 60);
  const s = whole % 60;
  const two = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${two(m)}:${two(s)}` : `${m}:${two(s)}`;
}

export function formatSize(bytes: number | null): string {
  if (bytes === null) return "";
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export type NewCall = {
  fileName: string;
  size: number;
  language: string;
  consent: boolean;
};

export type NewCallCheck =
  | { ok: true; body: NewCall }
  | { ok: false; fieldErrors: Record<string, string> };

/** Checks before anything is sent. The API checks all of it again, and more (the file's content). */
export function checkNewCall(input: {
  fileName: unknown;
  size: unknown;
  language: unknown;
  consent: unknown;
}): NewCallCheck {
  const fieldErrors: Record<string, string> = {};
  const fileName = typeof input.fileName === "string" ? input.fileName : "";
  const size = Number(input.size);
  const lower = fileName.toLowerCase();
  if (!fileName || !Number.isInteger(size) || size <= 0)
    fieldErrors.file = "Choose a recording.";
  else if (!AUDIO_EXTENSIONS.some((ext) => lower.endsWith(ext)))
    fieldErrors.file = `Only ${AUDIO_EXTENSIONS.join(", ")} files are accepted.`;
  else if (size > MAX_FILE_BYTES)
    fieldErrors.file = "The recording is larger than 100 MB.";
  const language = String(input.language ?? "");
  if (!CALL_LANGUAGES.some((l) => l.value === language))
    fieldErrors.language = "Choose the language of the call.";
  if (input.consent !== true)
    fieldErrors.consent =
      "Tick this only if the buyer agreed to the call being recorded.";
  if (Object.keys(fieldErrors).length > 0) return { ok: false, fieldErrors };
  return { ok: true, body: { fileName, size, language, consent: true } };
}

/** Plain words for the API's refusals. */
export function callErrorText(code: string | null, fallback: string): string {
  switch (code) {
    case "call_audio_unavailable":
      return "Call recordings are switched off for your organisation. An administrator can switch them on under AI agents.";
    case "call_limit_reached":
      return "Too many recordings were added just now. Try again later.";
    case "call_type_not_allowed":
      return `Only ${AUDIO_EXTENSIONS.join(", ")} files are accepted.`;
    case "call_too_large":
      return "The recording is larger than 100 MB.";
    case "call_not_audio":
      return "The file is not the kind of audio its name says. Export it again and try again.";
    case "call_not_received":
      return "The recording had not reached the store yet. Try again.";
    case "call_upload_expired":
      return "That upload took too long and was cancelled. Start again.";
    case "call_not_found":
    case "lead_not_found":
      return "That recording was not found.";
    case "call_audio_deleted":
      return "The audio of this recording was deleted.";
    case "call_not_ready":
      return "The recording is not ready to be played yet.";
    default:
      return fallback;
  }
}

export const callsPath = (leadId: string) => {
  if (!isUuid(leadId)) throw new Error("invalid lead");
  return `/leads/${leadId}`;
};

/** Only an absolute http(s) address is given to the audio player. */
export function safeAudioUrl(raw: string): string | null {
  try {
    const url = new URL(raw);
    return url.protocol === "https:" || url.protocol === "http:"
      ? url.toString()
      : null;
  } catch {
    return null;
  }
}
