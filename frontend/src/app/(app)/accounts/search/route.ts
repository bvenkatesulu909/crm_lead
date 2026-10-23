import { NextResponse, type NextRequest } from "next/server";

import { ApiError } from "@/lib/api-error";
import type { AccountPage } from "@/lib/api-types";
import { apiFetch } from "@/lib/server/api";

/**
 * GET /accounts/search?q=text - up to 20 accounts whose name matches, for the account picker.
 *
 * The browser never holds the API token, so it asks this route and the route asks the API.
 * The API alone decides which accounts the signed-in user may see; we only pass the text on
 * and return just the id and the name.
 */
export async function GET(request: NextRequest) {
  const q = (request.nextUrl.searchParams.get("q") ?? "").trim().slice(0, 100);
  const params = new URLSearchParams({ limit: "20" });
  if (q) params.set("q", q);
  try {
    const page = await apiFetch<AccountPage>(`/accounts?${params}`);
    return NextResponse.json(
      page.items.map((account) => ({ id: account.id, name: account.name })),
    );
  } catch (error) {
    if (error instanceof ApiError)
      return NextResponse.json(
        { error: error.problem.detail },
        { status: error.status },
      );
    throw error;
  }
}
