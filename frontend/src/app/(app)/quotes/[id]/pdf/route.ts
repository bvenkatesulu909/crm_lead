import { notFound } from "next/navigation";
import type { NextRequest } from "next/server";

import { apiDownloadLink } from "@/lib/server/api";
import { linkResponse } from "@/lib/server/file-response";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** GET /quotes/<id>/pdf - the stored PDF of a sent quote (the API checks access). */
export async function GET(
  request: NextRequest,
  { params }: RouteContext<"/quotes/[id]/pdf">,
) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  return linkResponse(
    await apiDownloadLink(`/quotes/${id}/pdf-link`),
    new URL(`/quotes/${id}`, request.nextUrl),
  );
}
