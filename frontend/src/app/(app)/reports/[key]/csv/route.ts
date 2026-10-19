import { notFound } from "next/navigation";
import type { NextRequest } from "next/server";

import { apiFile } from "@/lib/server/api";
import { fileResponse } from "@/lib/server/file-response";

const KEY = /^[a-z]{3,20}$/;
const PARAMS = ["start", "end", "owner_id"];

/** GET /reports/<key>/csv?start=&end=&owner_id= - the API applies the access rules. */
export async function GET(
  request: NextRequest,
  { params }: RouteContext<"/reports/[key]/csv">,
) {
  const { key } = await params;
  if (!KEY.test(key)) notFound();
  const query = new URLSearchParams();
  for (const name of PARAMS) {
    const value = request.nextUrl.searchParams.get(name);
    if (value) query.set(name, value);
  }
  // On a problem (bad dates, no access), go back to the report page with the same filters.
  const back = new URL("/reports", request.nextUrl);
  back.searchParams.set("report", key);
  for (const [name, value] of query) back.searchParams.set(name, value);
  return fileResponse(await apiFile(`/reports/${key}/csv?${query}`), back);
}
