import { notFound } from "next/navigation";
import type { NextRequest } from "next/server";

import { deckQuery, parseDeckFormat } from "@/lib/proposal-decks";
import { apiDownloadLink } from "@/lib/server/api";
import { linkResponse } from "@/lib/server/file-response";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * GET /quotes/<id>/deck[?format=pptx] - the newest proposal deck of a quote, as a PDF (the default)
 * or a PowerPoint file (the API checks access). Any other format is "not found".
 */
export async function GET(
  request: NextRequest,
  { params }: RouteContext<"/quotes/[id]/deck">,
) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  const format = parseDeckFormat(request.nextUrl.searchParams.get("format"));
  if (!format) notFound();
  return linkResponse(
    await apiDownloadLink(`/quotes/${id}/deck/link${deckQuery(format)}`),
    new URL(`/quotes/${id}`, request.nextUrl),
  );
}
