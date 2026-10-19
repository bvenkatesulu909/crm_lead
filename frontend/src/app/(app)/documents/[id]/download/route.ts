import { notFound } from "next/navigation";
import type { NextRequest } from "next/server";

import { apiFile } from "@/lib/server/api";
import { fileResponse } from "@/lib/server/file-response";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** GET /documents/<id>/download - the API checks access to the document's record. */
export async function GET(
  request: NextRequest,
  { params }: RouteContext<"/documents/[id]/download">,
) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  // On a problem, go back to the page the user came from (same site only).
  const referer = request.headers.get("referer");
  const back =
    referer && new URL(referer).origin === request.nextUrl.origin
      ? new URL(new URL(referer).pathname, request.nextUrl)
      : new URL("/", request.nextUrl);
  return fileResponse(await apiFile(`/documents/${id}/download`), back);
}
