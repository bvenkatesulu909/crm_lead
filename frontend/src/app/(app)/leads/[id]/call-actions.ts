"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import {
  CLIP_NOTE_MAX,
  CLIP_TITLE_MAX,
  callErrorText,
  callsPath,
  checkNewCall,
  checkNewClip,
  clipErrorText,
  safeAudioUrl,
  type CallClip,
  type CallDetail,
  type CallListen,
  type ClipInput,
} from "@/lib/calls";
import { isUuid } from "@/lib/communications";
import type { DialogState } from "@/lib/dialog-state";
import type { UploadTicket } from "@/lib/direct-upload";
import { apiFetch } from "@/lib/server/api";

/**
 * Call recording Server Actions (ADR 0030). The lead id comes from the page and is checked here;
 * the API decides who may read and write the lead and applies every rule again. Only the file's
 * NAME and SIZE reach the web app: the bytes go from the browser to the file store (ADR 0025), so
 * Netlify's request limit does not apply. What is sent to the API is built from a short list of
 * fields - never a tenant, a person, a status or a key.
 */

export type NewCallInfo = {
  fileName: string;
  size: number;
  language: string;
  consent: boolean;
};

export type StartResult =
  | { ticket: UploadTicket }
  | { fieldErrors: Record<string, string>; error: DialogState["error"] };

type CallTicket = {
  call_id: string;
  url: string;
  fields: Record<string, string>;
  expires_at: string;
  max_bytes: number;
};

function failure(previous: DialogState, error: unknown): DialogState {
  const info = toErrorInfo(error);
  return {
    attempt: previous.attempt + 1,
    fieldErrors: info.fieldErrors,
    error: { ...info, message: callErrorText(info.code, info.message) },
  };
}

/** Step 1: the API checks the lead, the switch, the consent, the name and size, and the limits. */
export async function startCallUpload(
  leadId: string,
  info: NewCallInfo,
): Promise<StartResult> {
  callsPath(leadId); // throws for a tampered id
  const checked = checkNewCall(info ?? {});
  if (!checked.ok) return { fieldErrors: checked.fieldErrors, error: null };
  try {
    const ticket = await apiFetch<CallTicket>(
      `/leads/${leadId}/calls/uploads`,
      {
        method: "POST",
        body: JSON.stringify({
          file_name: checked.body.fileName,
          size_bytes: checked.body.size,
          language: checked.body.language,
          consent: true,
        }),
      },
    );
    // The shared uploader calls the identifier "upload_id"; here it is the recording's id.
    return {
      ticket: {
        upload_id: ticket.call_id,
        url: ticket.url,
        fields: ticket.fields,
        expires_at: ticket.expires_at,
        max_bytes: ticket.max_bytes,
      },
    };
  } catch (error) {
    const problem = toErrorInfo(error);
    return {
      fieldErrors: problem.fieldErrors,
      error: {
        ...problem,
        message: callErrorText(problem.code, problem.message),
      },
    };
  }
}

/** Step 3: the file is in the store; the API reads the first bytes back and queues the work. */
export async function finishCallUpload(
  leadId: string,
  callId: string,
  previous: DialogState,
): Promise<DialogState> {
  const back = callsPath(leadId);
  if (!isUuid(callId)) throw new Error("invalid recording");
  try {
    await apiFetch(`/leads/${leadId}/calls/${callId}/finish`, {
      method: "POST",
    });
  } catch (error) {
    return failure(previous, error);
  }
  redirect(`${back}?done=call-added#calls`);
}

export async function deleteCallAudio(
  leadId: string,
  callId: string,
  previous: DialogState,
): Promise<DialogState> {
  const back = callsPath(leadId);
  if (!isUuid(callId)) throw new Error("invalid recording");
  try {
    await apiFetch(`/leads/${leadId}/calls/${callId}/audio`, {
      method: "DELETE",
    });
  } catch (error) {
    return failure(previous, error);
  }
  redirect(`${back}?done=call-audio-deleted#calls`);
}

export type Fetched<T> =
  { ok: true; value: T } | { ok: false; message: string };

/** A short link (60 seconds) to the cleaned audio. Each press asks again; nothing is kept. */
export async function listenToCall(
  leadId: string,
  callId: string,
): Promise<Fetched<CallListen>> {
  callsPath(leadId);
  if (!isUuid(callId)) throw new Error("invalid recording");
  try {
    const link = await apiFetch<CallListen>(
      `/leads/${leadId}/calls/${callId}/listen`,
    );
    const url = safeAudioUrl(link.url);
    if (!url) return { ok: false, message: "The audio could not be opened." };
    return { ok: true, value: { ...link, url } };
  } catch (error) {
    const info = toErrorInfo(error);
    return { ok: false, message: callErrorText(info.code, info.message) };
  }
}

/** The transcript is read only when someone opens it (the list stays light). */
export async function readCallTranscript(
  leadId: string,
  callId: string,
): Promise<Fetched<CallDetail>> {
  callsPath(leadId);
  if (!isUuid(callId)) throw new Error("invalid recording");
  try {
    const detail = await apiFetch<CallDetail>(
      `/leads/${leadId}/calls/${callId}`,
    );
    return { ok: true, value: detail };
  } catch (error) {
    const info = toErrorInfo(error);
    return { ok: false, message: callErrorText(info.code, info.message) };
  }
}

// --- highlight clips (ADR 0033) ---------------------------------------------------------------

const clipsPath = (leadId: string, callId: string) => {
  callsPath(leadId);
  if (!isUuid(callId)) throw new Error("invalid recording");
  return `/leads/${leadId}/calls/${callId}/clips`;
};

function clipProblem(error: unknown): { ok: false; message: string } {
  const info = toErrorInfo(error);
  return { ok: false, message: clipErrorText(info.code, info.message) };
}

export async function readClips(
  leadId: string,
  callId: string,
): Promise<Fetched<CallClip[]>> {
  const path = clipsPath(leadId, callId);
  try {
    const page = await apiFetch<{ items: CallClip[] }>(path);
    return { ok: true, value: page.items };
  } catch (error) {
    return clipProblem(error);
  }
}

/** Only the moment and the two texts are sent; the server decides everything else. */
export async function createClip(
  leadId: string,
  callId: string,
  input: ClipInput,
): Promise<Fetched<CallClip>> {
  const path = clipsPath(leadId, callId);
  const checked = checkNewClip({
    start: String(input?.start ?? ""),
    end: String(input?.end ?? ""),
    title: String(input?.title ?? ""),
    note: String(input?.note ?? ""),
    duration: typeof input?.duration === "number" ? input.duration : null,
  });
  if (!checked.ok)
    return { ok: false, message: Object.values(checked.fieldErrors)[0] };
  try {
    const made = await apiFetch<CallClip>(path, {
      method: "POST",
      body: JSON.stringify(checked.body),
    });
    return { ok: true, value: made };
  } catch (error) {
    return clipProblem(error);
  }
}

export async function editClip(
  leadId: string,
  callId: string,
  clipId: string,
  input: { title: string; note: string },
): Promise<Fetched<CallClip>> {
  const path = clipsPath(leadId, callId);
  if (!isUuid(clipId)) throw new Error("invalid clip");
  const title = String(input?.title ?? "").trim();
  const note = String(input?.note ?? "").trim();
  if (!title) return { ok: false, message: "Give the clip a title." };
  if (title.length > CLIP_TITLE_MAX)
    return {
      ok: false,
      message: `The title is longer than ${CLIP_TITLE_MAX} characters.`,
    };
  if (note.length > CLIP_NOTE_MAX)
    return {
      ok: false,
      message: `The note is longer than ${CLIP_NOTE_MAX} characters.`,
    };
  try {
    const changed = await apiFetch<CallClip>(`${path}/${clipId}`, {
      method: "PATCH",
      body: JSON.stringify({ title, note: note || null }),
    });
    return { ok: true, value: changed };
  } catch (error) {
    return clipProblem(error);
  }
}

export async function deleteClip(
  leadId: string,
  callId: string,
  clipId: string,
): Promise<Fetched<null>> {
  const path = clipsPath(leadId, callId);
  if (!isUuid(clipId)) throw new Error("invalid clip");
  try {
    await apiFetch(`${path}/${clipId}`, { method: "DELETE" });
    return { ok: true, value: null };
  } catch (error) {
    return clipProblem(error);
  }
}

/** A short link (60 seconds) to one clip. Each press asks again; nothing is kept. */
export async function listenToClip(
  leadId: string,
  callId: string,
  clipId: string,
): Promise<Fetched<CallListen>> {
  const path = clipsPath(leadId, callId);
  if (!isUuid(clipId)) throw new Error("invalid clip");
  try {
    const link = await apiFetch<CallListen>(`${path}/${clipId}/listen`);
    const url = safeAudioUrl(link.url);
    if (!url) return { ok: false, message: "The audio could not be opened." };
    return { ok: true, value: { ...link, url } };
  } catch (error) {
    return clipProblem(error);
  }
}
