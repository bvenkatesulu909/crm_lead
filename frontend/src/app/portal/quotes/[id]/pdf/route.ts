import { notFound } from "next/navigation";
import type { NextRequest } from "next/server";

import { apiDownloadLink } from "@/lib/server/api";
import { linkResponse } from "@/lib/server/file-response";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** GET /portal/quotes/<id>/pdf - a customer's copy of a quote sent to their company. */
export async function GET(
  request: NextRequest,
  { params }: RouteContext<"/portal/quotes/[id]/pdf">,
) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  return linkResponse(
    await apiDownloadLink(`/portal/quotes/${id}/pdf-link`),
    new URL(`/portal/quotes/${id}`, request.nextUrl),
  );
}
