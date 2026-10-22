import "server-only";

import { cookies } from "next/headers";

import { serverConfig } from "@/lib/server/config";
import { SESSION_COOKIE, decryptSession } from "@/lib/server/session";

export async function POST(request: Request) {
  const body = (await request.json().catch(() => null)) as { text?: unknown } | null;
  const text = typeof body?.text === "string" ? body.text.trim() : "";
  if (!text || text.length > 2000) return Response.json({ detail: "Invalid text." }, { status: 400 });
  const config = serverConfig();
  const session = await decryptSession((await cookies()).get(SESSION_COOKIE)?.value, config.SESSION_SECRET);
  if (!session) return Response.json({ detail: "Not signed in." }, { status: 401 });
  const upstream = await fetch(config.API_BASE_URL + "/voice/speak", {
    method: "POST",
    headers: { Authorization: "Bearer " + session.accessToken, "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
    cache: "no-store",
    signal: AbortSignal.timeout(60000),
  });
  if (!upstream.ok) {
    return Response.json(await upstream.json().catch(() => ({ detail: "Voice unavailable." })), { status: upstream.status });
  }
  return new Response(upstream.body, {
    headers: { "Content-Type": upstream.headers.get("content-type") ?? "audio/mpeg", "Cache-Control": "no-store" },
  });
}
