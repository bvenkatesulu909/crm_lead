import { notFound } from "next/navigation";
import type { NextRequest } from "next/server";

import { apiDownloadLink } from "@/lib/server/api";
import { linkResponse } from "@/lib/server/file-response";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** GET /photos/copies/<id>/download - a finished adjusted copy (the API checks access). */
export async function GET(
  request: NextRequest,
  { params }: RouteContext<"/photos/copies/[id]/download">,
) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  return linkResponse(
    await apiDownloadLink(`/photo-enhancer/enhancements/${id}/link`),
    new URL("/", request.nextUrl),
  );
}
