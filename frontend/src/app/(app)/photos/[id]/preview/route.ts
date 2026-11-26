import type { NextRequest } from "next/server";

import { apiStream } from "@/lib/server/api";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * POST /photos/<id>/preview - what the adjustments would do, as a small JPEG. The browser sends
 * only the adjustments; the token stays on this server. The API checks the person, the photo, the
 * caps and the rate limit; its answer is passed on (a picture, or a problem with its code).
 */
export async function POST(
  request: NextRequest,
  { params }: RouteContext<"/photos/[id]/preview">,
) {
  const { id } = await params;
  if (!UUID.test(id))
    return Response.json({ detail: "Not found." }, { status: 404 });
  const body = (await request.json().catch(() => null)) as {
    operations?: unknown;
  } | null;
  const operations =
    body && typeof body.operations === "object" && body.operations !== null
      ? body.operations
      : {};
  const response = await apiStream("/photo-enhancer/previews", {
    document_id: id,
    operations,
  });
  if (response.ok && response.headers.get("content-type") === "image/jpeg")
    return new Response(await response.arrayBuffer(), {
      headers: {
        "Content-Type": "image/jpeg",
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
      },
    });
  const problem = (await response.json().catch(() => null)) as {
    detail?: string;
    code?: string;
  } | null;
  return Response.json(
    {
      detail: problem?.detail ?? "Preview failed.",
      code: problem?.code ?? null,
    },
    { status: response.ok ? 502 : response.status },
  );
}
