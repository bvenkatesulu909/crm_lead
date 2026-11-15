import "server-only";

import { NextResponse } from "next/server";

import type { ApiFile, ApiLink } from "@/lib/server/api";

/**
 * Turns an API file into the browser's download. Problems go back to the page the user came
 * from with a message (`?file=...`), instead of showing a raw error.
 */
export function fileResponse(file: ApiFile, backTo: URL): Response {
  if (file.ok)
    return new Response(file.data, {
      headers: {
        "Content-Type": file.contentType,
        "Content-Disposition": `attachment; filename="${file.fileName}"`,
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
      },
    });
  return problemResponse(file.status, backTo);
}

/**
 * Sends the browser to a short-lived link in the file store (ADR 0025). The link is not cached
 * and the store does not learn which page it came from.
 */
export function linkResponse(link: ApiLink, backTo: URL): Response {
  if (!link.ok) return problemResponse(link.status, backTo);
  const response = NextResponse.redirect(link.url, 302);
  response.headers.set("Cache-Control", "private, no-store");
  response.headers.set("Referrer-Policy", "no-referrer");
  return response;
}

function problemResponse(status: number, backTo: URL): Response {
  if (status === 401) return NextResponse.redirect(new URL("/login", backTo));
  const reason =
    status === 404 || status === 403
      ? "missing"
      : status === 409
        ? "not-sent"
        : "unavailable";
  backTo.searchParams.set("file", reason);
  return NextResponse.redirect(backTo);
}
