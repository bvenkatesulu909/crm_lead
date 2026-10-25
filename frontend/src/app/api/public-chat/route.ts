import "server-only";

import { cookies, headers } from "next/headers";

import { checkVisitorMessage } from "@/lib/public-chat";
import { serverConfig } from "@/lib/server/config";
import {
  CHAT_COOKIE,
  chatCookieOptions,
  forwardChat,
  publicChatKey,
  visitorIp,
} from "@/lib/server/public-chat";

/**
 * POST /api/public-chat - a website visitor's message (ADR 0013). Public: no sign-in, so the
 * proxy lets it through. Without PUBLIC_CHAT_SERVER_KEY the chat is switched off (404).
 */
export async function POST(request: Request) {
  const key = publicChatKey();
  if (!key) return Response.json({ code: "not_found" }, { status: 404 });

  const body = (await request.json().catch(() => null)) as {
    message?: unknown;
    website?: unknown;
  } | null;
  const message = typeof body?.message === "string" ? body.message.trim() : "";
  const problem = checkVisitorMessage(message);
  if (problem)
    return Response.json({ code: "invalid", detail: problem }, { status: 422 });
  const website =
    typeof body?.website === "string" ? body.website.slice(0, 500) : "";

  const config = serverConfig();
  const jar = await cookies();
  const result = await forwardChat({
    message,
    website,
    token: jar.get(CHAT_COOKIE)?.value,
    ip: visitorIp(await headers()),
    key,
    apiBaseUrl: config.API_BASE_URL,
  });
  if (result.cookie !== "keep") {
    jar.set(
      CHAT_COOKIE,
      result.cookie.set,
      chatCookieOptions(config.secureCookies),
    );
  }
  return Response.json(result.body, {
    status: result.status,
    headers: { "Cache-Control": "no-store" },
  });
}
