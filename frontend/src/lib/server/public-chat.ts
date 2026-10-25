import "server-only";

import { isIP } from "node:net";

import type { ChatAnswer, ChatProblem } from "@/lib/public-chat";

/**
 * The Next.js side of the public website chat (ADR 0013, decisions 3 and 4).
 *
 * The browser talks only to /api/public-chat. This server adds the secret server key and the
 * visitor's address, and keeps the conversation token in an httpOnly cookie - page JavaScript
 * can never read the token, and the API can't be called directly from the internet.
 */
export const CHAT_COOKIE = "crm_chat";
const TOKEN = /^[A-Za-z0-9_-]{40,100}$/;
// Conversations without a lead are deleted after 30 quiet days; the cookie lasts as long.
const COOKIE_DAYS = 30;

/** The secret shared with the API, or null when the chat is switched off here. */
export function publicChatKey(): string | null {
  const key = process.env.PUBLIC_CHAT_SERVER_KEY?.trim() ?? "";
  return key.length >= 32 ? key : null;
}

export function chatCookieOptions(secure: boolean) {
  return {
    httpOnly: true,
    secure,
    sameSite: "lax" as const,
    // Sent only to the chat route, never to the CRM pages.
    path: "/api/public-chat",
    maxAge: COOKIE_DAYS * 24 * 60 * 60,
  };
}

/** The visitor's address as the hosting proxy saw it ("" if unknown or not an address). */
export function visitorIp(headers: Headers): string {
  // Netlify sets this one itself; a visitor can add their own X-Forwarded-For to dodge the
  // per-address limits, so it only counts when the platform header is missing (local runs).
  const platform = headers.get("x-nf-client-connection-ip")?.trim();
  const forwarded = headers.get("x-forwarded-for")?.split(",")[0]?.trim();
  const candidate =
    platform || forwarded || headers.get("x-real-ip")?.trim() || "";
  return isIP(candidate) ? candidate : "";
}

export type ForwardResult = {
  status: number;
  body: ChatAnswer | ChatProblem;
  /** What to do with the crm_chat cookie. */
  cookie: { set: string } | "keep";
};

type Fetcher = (
  url: string,
  init: RequestInit & { headers: Record<string, string> },
) => Promise<Response>;

/** Send one visitor message to the API and translate the answer for the browser. */
export async function forwardChat(
  input: {
    message: string;
    website: string;
    token: string | null | undefined;
    ip: string;
    key: string;
    apiBaseUrl: string;
  },
  fetcher: Fetcher = fetch,
): Promise<ForwardResult> {
  const send = (token: string | null) =>
    fetcher(input.apiBaseUrl + "/public/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Public-Chat-Key": input.key,
        "X-Visitor-Ip": input.ip,
      },
      body: JSON.stringify({
        ...(token ? { token } : {}),
        message: input.message,
        website: input.website,
      }),
      cache: "no-store",
      signal: AbortSignal.timeout(60000),
    });

  const token = input.token && TOKEN.test(input.token) ? input.token : null;
  let response: Response;
  try {
    response = await send(token);
    let problem = response.ok ? null : await readJson<ChatProblem>(response);
    if (
      token &&
      response.status === 404 &&
      problem?.code === "conversation_not_found"
    ) {
      // The old conversation was cleaned up: start a new one with the same message.
      response = await send(null);
      problem = response.ok ? null : await readJson<ChatProblem>(response);
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
  const data = await readJson<{
    token?: string;
    reply?: string;
    lead_saved?: boolean;
  }>(response);
  if (!data?.token || typeof data.reply !== "string") {
    return { status: 503, body: { code: "unavailable" }, cookie: "keep" };
  }
  return {
    status: 200,
    body: { reply: data.reply, lead_saved: data.lead_saved === true },
    cookie: { set: data.token },
  };
}

async function readJson<T>(response: Response): Promise<T | null> {
  return (await response.json().catch(() => null)) as T | null;
}
