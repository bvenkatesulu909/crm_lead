/**
 * Sends a file from the browser straight to the file store (ADR 0025, step DU4).
 *
 * Why: the web app runs on Netlify, which refuses any request of 6 MB or more. So the file does
 * not pass through the web app: the CRM API checks everything it can first and hands back a
 * "ticket" - a signed link that is valid for five minutes, for ONE object, and that the store
 * itself enforces (exact name, type and maximum size). The browser posts the file there, then
 * asks the API to finish; the API reads the file back and runs every normal check on it.
 *
 * The ticket holds no token or store key: only the fields the store needs for that one object.
 */

import type { ApiErrorInfo } from "@/lib/api-error";

/** What `POST /documents/uploads` and `POST /knowledge/uploads` answer. */
export type UploadTicket = {
  upload_id: string;
  url: string;
  fields: Record<string, string>;
  expires_at: string;
  max_bytes: number;
};

/** How sending ended; each one gets its own message for people. */
export type SendResult =
  "sent" | "refused" | "unreachable" | "bad_ticket" | "too_large";

export const SEND_MESSAGES: Record<Exclude<SendResult, "sent">, string> = {
  refused:
    "The file store refused the file. Start the upload again; if it keeps failing, tell your administrator.",
  unreachable:
    "The file store could not be reached. Check your connection and try again.",
  bad_ticket: "The upload could not be prepared. Please try again.",
  too_large:
    "The file is larger than the size that was announced. Choose the file again.",
};

/** Only an absolute http(s) address is followed; anything else is refused before sending. */
export function safeStoreUrl(raw: string): string | null {
  try {
    const url = new URL(raw);
    return url.protocol === "https:" || url.protocol === "http:"
      ? url.toString()
      : null;
  } catch {
    return null;
  }
}

/** The form a POST policy expects: every signed field first, in order, the file LAST. */
export function storeForm(ticket: UploadTicket, file: Blob): FormData {
  const body = new FormData();
  for (const [key, value] of Object.entries(ticket.fields))
    body.append(key, value);
  body.append("file", file);
  return body;
}

type Xhr = Pick<
  XMLHttpRequest,
  | "open"
  | "send"
  | "abort"
  | "status"
  | "onload"
  | "onerror"
  | "ontimeout"
  | "upload"
  | "timeout"
>;

/**
 * Posts the file and reports progress from 0 to 100. Never rejects: the result says what
 * happened. `makeRequest` exists for tests; the browser's own XMLHttpRequest is used otherwise
 * (fetch cannot report upload progress).
 */
export function sendToStore(
  ticket: UploadTicket,
  file: Blob,
  onProgress: (percent: number) => void,
  makeRequest: () => Xhr = () => new XMLHttpRequest(),
): Promise<SendResult> {
  const url = safeStoreUrl(ticket.url);
  if (!url || typeof ticket.fields !== "object" || ticket.fields === null)
    return Promise.resolve("bad_ticket");
  if (file.size > ticket.max_bytes) return Promise.resolve("too_large");
  return new Promise((resolve) => {
    const request = makeRequest();
    request.open("POST", url);
    // A 20 MB file on a slow line: generous, but a stuck request still ends.
    request.timeout = 10 * 60 * 1000;
    request.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0)
        onProgress(
          Math.min(100, Math.round((event.loaded / event.total) * 100)),
        );
    };
    request.onload = () => {
      // A POST policy answers 204 (or 200/201). Anything else - including a redirect, which is
      // how SeaweedFS refuses - means the file was not stored.
      if (request.status >= 200 && request.status < 300) {
        onProgress(100);
        resolve("sent");
      } else resolve(request.status === 0 ? "unreachable" : "refused");
    };
    request.onerror = () => resolve("unreachable");
    request.ontimeout = () => resolve("unreachable");
    request.send(storeForm(ticket, file));
  });
}

/** A message from the browser's side (no API answer), shaped like the API's own errors. */
export function storeError(result: Exclude<SendResult, "sent">): ApiErrorInfo {
  return {
    status: 0,
    message: SEND_MESSAGES[result],
    code: `store_${result}`,
    requestId: null,
    fieldErrors: {},
  };
}

type Started =
  | { ticket: UploadTicket }
  | { fieldErrors: Record<string, string>; error: ApiErrorInfo | null };

export type DirectUploadOutcome<R> =
  | { ok: true; result: R }
  | {
      ok: false;
      fieldErrors: Record<string, string>;
      error: ApiErrorInfo | null;
    };

/**
 * The three steps in order: ask the API (start), send the bytes to the store, ask the API to
 * finish. Stops at the first step that fails and says why. `finish` may redirect (a Server
 * Action does that on success) - that is not caught here.
 */
export async function directUpload<R>(
  file: Blob,
  start: () => Promise<Started>,
  finish: (uploadId: string) => Promise<R>,
  onProgress: (percent: number) => void,
  send: typeof sendToStore = sendToStore,
): Promise<DirectUploadOutcome<R>> {
  const started = await start();
  if (!("ticket" in started))
    return {
      ok: false,
      fieldErrors: started.fieldErrors,
      error: started.error,
    };
  const sent = await send(started.ticket, file, onProgress);
  if (sent !== "sent")
    return { ok: false, fieldErrors: {}, error: storeError(sent) };
  return { ok: true, result: await finish(started.ticket.upload_id) };
}
