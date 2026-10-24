import { NextResponse, type NextRequest } from "next/server";

import { ApiError } from "@/lib/api-error";
import type { AccountPage } from "@/lib/api-types";
import { apiFetch } from "@/lib/server/api";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * GET /accounts/search?q=text - up to 20 accounts whose name matches, for the account picker.
 *
 * The browser never holds the API token, so it asks this route and the route asks the API.
 * The API alone decides which accounts the signed-in user may see; we only pass the text on
 * and return just the id and the name. `exclude=<id>` leaves one account out of the matches
 * (an account cannot be its own parent).
 */
export async function GET(request: NextRequest) {
  const q = (request.nextUrl.searchParams.get("q") ?? "").trim().slice(0, 100);
  const excluded = request.nextUrl.searchParams.get("exclude") ?? "";
  const skip = UUID.test(excluded) ? excluded : null;
  const params = new URLSearchParams({ limit: skip ? "21" : "20" });
  if (q) params.set("q", q);
  try {
    const page = await apiFetch<AccountPage>(`/accounts?${params}`);
    return NextResponse.json(
      page.items
        .filter((account) => account.id !== skip)
        .slice(0, 20)
        .map((account) => ({ id: account.id, name: account.name })),
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
