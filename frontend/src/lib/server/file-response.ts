import "server-only";

import { NextResponse } from "next/server";

import type { ApiFile } from "@/lib/server/api";

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
  if (file.status === 401)
    return NextResponse.redirect(new URL("/login", backTo));
  const reason =
    file.status === 404 || file.status === 403
      ? "missing"
      : file.status === 409
        ? "not-sent"
        : "unavailable";
  backTo.searchParams.set("file", reason);
  return NextResponse.redirect(backTo);
}
