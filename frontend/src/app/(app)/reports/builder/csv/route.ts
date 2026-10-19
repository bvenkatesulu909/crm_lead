import type { NextRequest } from "next/server";

import { apiFile } from "@/lib/server/api";
import { fileResponse } from "@/lib/server/file-response";

const TYPE = /^[a-z]{3,20}$/;

/** GET /reports/builder/csv?type=&columns=&start=&end=&owner_id=&status= (audited by the API). */
export async function GET(request: NextRequest) {
  const source = request.nextUrl.searchParams;
  const type = source.get("type") ?? "";
  const back = new URL("/reports/builder", request.nextUrl);
  for (const [name, value] of source) back.searchParams.set(name, value);
  if (!TYPE.test(type)) return fileResponse({ ok: false, status: 404 }, back);
  const query = new URLSearchParams();
  for (const column of source.getAll("columns"))
    query.append("columns", column);
  for (const name of ["start", "end", "owner_id", "status"]) {
    const value = source.get(name);
    if (value) query.set(name, value);
  }
  return fileResponse(
    await apiFile(`/reports/builder/${type}/csv?${query}`),
    back,
  );
}
