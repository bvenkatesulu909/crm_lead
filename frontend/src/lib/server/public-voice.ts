import "server-only";

import { isChatLanguage } from "@/lib/public-chat";
import type { VoiceAnswer, VoiceProblem } from "@/lib/public-voice";

/**
 * The Next.js side of the voice receptionist (ADR 0038, VR4). Like the typed chat, the browser
 * talks only to our own route; this server adds the secret server key and the visitor's address,
 * and the conversation token stays in the httpOnly cookie of the typed chat.
 */
const TOKEN = /^[A-Za-z0-9_-]{40,100}$/;

/** Whether the voice button is offered on /chat: off unless this server says so. */
export function publicVoiceEnabled(): boolean {
  return process.env.PUBLIC_CHAT_VOICE?.trim().toLowerCase() === "on";
}

/** The notice version the page shows. It must equal the API's CRM_RECEPTIONIST_NOTICE_VERSION. */
export function voiceNoticeVersion(): number {
  const value = Number.parseInt(
    process.env.PUBLIC_CHAT_VOICE_NOTICE_VERSION ?? "1",
    10,
  );
  return Number.isInteger(value) && value >= 1 && value <= 10000 ? value : 1;
}

export type VoiceForwardResult = {
  status: number;
  body: VoiceAnswer | VoiceProblem;
  /** What to do with the crm_chat cookie. */
  cookie: { set: string } | "keep";
};

type Fetcher = (
  url: string,
  init: RequestInit & { headers: Record<string, string> },
) => Promise<Response>;

async function readJson<T>(response: Response): Promise<T | null> {
  return (await response.json().catch(() => null)) as T | null;
}

/** Send one spoken turn to the API and translate the answer for the browser. */
export async function forwardVoiceTurn(
  input: {
    audio: Blob;
    filename: string;
    language?: string;
    consentVersion: number | null;
    website: string;
    token: string | null | undefined;
    ip: string;
    key: string;
    apiBaseUrl: string;
  },
  fetcher: Fetcher = fetch,
): Promise<VoiceForwardResult> {
  const send = (token: string | null) => {
    const form = new FormData();
    form.set("audio", input.audio, input.filename);
    form.set(
      "language",
      isChatLanguage(input.language) ? input.language : "en",
    );
    if (input.consentVersion !== null)
      form.set("consent_version", String(input.consentVersion));
    form.set("website", input.website);
    if (token) form.set("token", token);
    return fetcher(input.apiBaseUrl + "/public/voice/turn", {
      method: "POST",
      // No Content-Type here: fetch adds the multipart boundary itself.
      headers: { "X-Public-Chat-Key": input.key, "X-Visitor-Ip": input.ip },
      body: form,
      cache: "no-store",
      signal: AbortSignal.timeout(60000),
    });
  };

  const token = input.token && TOKEN.test(input.token) ? input.token : null;
  let response: Response;
  try {
    response = await send(token);
    let problem = response.ok ? null : await readJson<VoiceProblem>(response);
    if (
      token &&
      response.status === 404 &&
      problem?.code === "conversation_not_found"
    ) {
      // The old conversation was cleaned up: start a new one (the page sends its consent each turn).
      response = await send(null);
      problem = response.ok ? null : await readJson<VoiceProblem>(response);
    }
    if (problem) {
      return {
        status: response.status,
        body: { code: problem.code, detail: problem.detail },
        cookie: "keep",
      };
    }
  } catch {
    return { status: 503, body: { code: "unavailable" }, cookie: "keep" };
  }
  const data = await readJson<Partial<VoiceAnswer> & { token?: string }>(
    response,
  );
  if (!data?.token || typeof data.reply !== "string") {
    return { status: 503, body: { code: "unavailable" }, cookie: "keep" };
  }
  return {
    status: 200,
    body: {
      heard: typeof data.heard === "string" ? data.heard : "",
      reply: data.reply,
      lead_saved: data.lead_saved === true,
      audio_base64:
        typeof data.audio_base64 === "string" ? data.audio_base64 : null,
      audio_type: typeof data.audio_type === "string" ? data.audio_type : null,
      seconds_left: Number(data.seconds_left ?? 0),
      turns_left: Number(data.turns_left ?? 0),
      call_ended: data.call_ended === true,
    },
    cookie: { set: data.token },
  };
}
