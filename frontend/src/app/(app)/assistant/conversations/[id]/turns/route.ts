import type { NextRequest } from "next/server";

import { apiStream } from "@/lib/server/api";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * POST /assistant/conversations/<id>/turns - ask the next question (ADR 0023).
 *
 * Only the question, the answer mode and an optional ticket reference are passed on - nothing
 * else the browser sends reaches the API (the API refuses extra fields anyway). The answer is a
 * stream of Server-Sent Events that is handed through as it arrives, so the first sentence can be
 * shown and spoken while the model is still writing.
 */
export async function POST(
  request: NextRequest,
  { params }: RouteContext<"/assistant/conversations/[id]/turns">,
) {
  const { id } = await params;
  if (!UUID.test(id))
    return Response.json({ detail: "Not found." }, { status: 404 });
  const body = (await request.json().catch(() => null)) as Record<
    string,
    unknown
  > | null;
  const question =
    typeof body?.question === "string" ? body.question.trim() : "";
  if (!question || question.length > 2000) {
    return Response.json(
      { detail: "Please type or say a question." },
      { status: 422 },
    );
  }
  const mode = body?.mode === "voice" ? "voice" : "text";
  const ticket =
    typeof body?.ticket_id === "string"
      ? body.ticket_id.slice(0, 40)
      : undefined;
  const upstream = await apiStream(
    `/assistant/conversations/${id}/turns`,
    { question, mode, ...(ticket ? { ticket_id: ticket } : {}) },
    request.signal,
  );
  if (!upstream.ok || !upstream.body) {
    const problem = await upstream
      .json()
      .catch(() => ({ detail: "The assistant is unavailable." }));
    return Response.json(problem, {
      status: upstream.ok ? 502 : upstream.status,
    });
  }
  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-store, no-transform",
      "X-Accel-Buffering": "no",
    },
  });
}
