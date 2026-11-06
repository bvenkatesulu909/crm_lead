import { NextResponse } from "next/server";

import { ApiError } from "@/lib/api-error";
import { apiFetch } from "@/lib/server/api";

/**
 * POST /assistant/conversations - start a conversation with the staff assistant (ADR 0023).
 * The API creates it for the signed-in employee; the browser only gets its id.
 */
export async function POST() {
  try {
    const conversation = await apiFetch<{ id: string }>(
      "/assistant/conversations",
      {
        method: "POST",
      },
    );
    return NextResponse.json(
      { id: conversation.id },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 503;
    return NextResponse.json(
      { detail: "Could not start a conversation." },
      { status },
    );
  }
}
