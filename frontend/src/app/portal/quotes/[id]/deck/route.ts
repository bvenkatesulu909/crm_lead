import { notFound } from "next/navigation";
import type { NextRequest } from "next/server";

import { apiDownloadLink } from "@/lib/server/api";
import { linkResponse } from "@/lib/server/file-response";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** GET /portal/quotes/<id>/deck - the proposal deck of a quote sent to the customer's company. */
export async function GET(
  request: NextRequest,
  { params }: RouteContext<"/portal/quotes/[id]/deck">,
) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  return linkResponse(
    await apiDownloadLink(`/portal/quotes/${id}/deck/link`),
    new URL(`/portal/quotes/${id}`, request.nextUrl),
  );
}
