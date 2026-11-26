import "server-only";

import { cookies, headers } from "next/headers";

import { VOICE_AUDIO_TYPES, VOICE_MAX_AUDIO_BYTES } from "@/lib/public-voice";
import { serverConfig } from "@/lib/server/config";
import {
  CHAT_COOKIE,
  chatCookieOptions,
  publicChatKey,
  visitorIp,
} from "@/lib/server/public-chat";
import {
  forwardVoiceTurn,
  publicVoiceEnabled,
} from "@/lib/server/public-voice";

/**
 * POST /api/public-chat/voice - one spoken turn of a website visitor (ADR 0038). Public: no
 * sign-in. Without PUBLIC_CHAT_SERVER_KEY, or while PUBLIC_CHAT_VOICE is not "on", it does not
 * exist (404). The conversation cookie is the same one the typed chat uses.
 */
export async function POST(request: Request) {
  const key = publicChatKey();
  if (!key || !publicVoiceEnabled())
    return Response.json({ code: "not_found" }, { status: 404 });

  const form = await request.formData().catch(() => null);
  const audio = form?.get("audio");
  if (!(audio instanceof Blob))
    return Response.json({ code: "invalid" }, { status: 422 });
  // The same limits the API applies: one turn is a few seconds of speech.
  const type = audio.type.split(";")[0]?.trim().toLowerCase() ?? "";
  if (
    audio.size === 0 ||
    audio.size > VOICE_MAX_AUDIO_BYTES ||
    !(VOICE_AUDIO_TYPES as readonly string[]).includes(type)
  )
    return Response.json({ code: "invalid" }, { status: 422 });

  const language = form?.get("language");
  const consent = Number.parseInt(
    String(form?.get("consent_version") ?? ""),
    10,
  );
  const website = form?.get("website");
  const config = serverConfig();
  const jar = await cookies();
  const result = await forwardVoiceTurn({
    audio,
    filename: type === "audio/mp4" ? "turn.m4a" : "turn.webm",
    language: typeof language === "string" ? language : "en",
    consentVersion: Number.isInteger(consent) && consent >= 1 ? consent : null,
    website: typeof website === "string" ? website.slice(0, 500) : "",
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
