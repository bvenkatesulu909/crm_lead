"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import {
  callErrorText,
  callsPath,
  checkNewCall,
  safeAudioUrl,
  type CallDetail,
  type CallListen,
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
