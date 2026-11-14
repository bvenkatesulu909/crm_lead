import { notFound } from "next/navigation";
import type { NextRequest } from "next/server";

import { deckQuery, parseDeckFormat } from "@/lib/proposal-decks";
import { apiDownloadLink } from "@/lib/server/api";
import { linkResponse } from "@/lib/server/file-response";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * GET /portal/quotes/<id>/deck[?format=pptx] - the proposal deck (PDF, or PowerPoint with the
 * format) of a quote sent to the customer's company. Any other format is "not found".
 */
export async function GET(
  request: NextRequest,
  { params }: RouteContext<"/portal/quotes/[id]/deck">,
) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  const format = parseDeckFormat(request.nextUrl.searchParams.get("format"));
  if (!format) notFound();
  return linkResponse(
    await apiDownloadLink(`/portal/quotes/${id}/deck/link${deckQuery(format)}`),
    new URL(`/portal/quotes/${id}`, request.nextUrl),
  );
}
