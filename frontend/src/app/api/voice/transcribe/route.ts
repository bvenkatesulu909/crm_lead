import "server-only";

import { cookies } from "next/headers";

import { serverConfig } from "@/lib/server/config";
import { SESSION_COOKIE, decryptSession } from "@/lib/server/session";

export async function POST(request: Request) {
  const form = await request.formData();
  const file = form.get("file");
  if (!(file instanceof File)) return Response.json({ detail: "Audio required." }, { status: 400 });
  const config = serverConfig();
  const session = await decryptSession((await cookies()).get(SESSION_COOKIE)?.value, config.SESSION_SECRET);
  if (!session) return Response.json({ detail: "Not signed in." }, { status: 401 });
  const upstream = await fetch(config.API_BASE_URL + "/voice/transcribe", {
    method: "POST",
    headers: { Authorization: "Bearer " + session.accessToken },
    body: form,
    cache: "no-store",
    signal: AbortSignal.timeout(60000),
  });
  if (!upstream.ok) {
    return Response.json(await upstream.json().catch(() => ({ detail: "Voice unavailable." })), { status: upstream.status });
  }
  return Response.json(await upstream.json(), { headers: { "Cache-Control": "no-store" } });
}
