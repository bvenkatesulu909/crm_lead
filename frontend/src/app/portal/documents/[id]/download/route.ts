import { notFound } from "next/navigation";
import type { NextRequest } from "next/server";

import { apiFile } from "@/lib/server/api";
import { fileResponse } from "@/lib/server/file-response";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** GET /portal/documents/<id>/download - only files shared with the customer's company. */
export async function GET(
  request: NextRequest,
  { params }: RouteContext<"/portal/documents/[id]/download">,
) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  const referer = request.headers.get("referer");
  const back =
    referer && new URL(referer).origin === request.nextUrl.origin
      ? new URL(new URL(referer).pathname, request.nextUrl)
      : new URL("/portal", request.nextUrl);
  return fileResponse(await apiFile(`/portal/documents/${id}/download`), back);
}
