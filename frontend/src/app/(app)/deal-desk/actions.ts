"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import { dealDeskErrorText, opportunityPath } from "@/lib/deal-desk";
import type { DialogState } from "@/lib/dialog-state";
import { apiFetch } from "@/lib/server/api";

/**
 * Server Action of the deal desk (ADR 0024). The deal id comes from the browser, so it is
 * untrusted - that is fine: the API checks that the person may read the deal and may ask the
 * deal desk. The organisation and the person are never sent. This code only turns the API's codes
 * into plain words and goes back to the deal.
 */
export async function askDealDesk(
  opportunityId: string,
  previous: DialogState,
): Promise<DialogState> {
  const back = opportunityPath(opportunityId); // throws for a tampered id
  try {
    await apiFetch("/deal-desk/reviews", {
      method: "POST",
      body: JSON.stringify({ opportunity_id: opportunityId }),
      // Four model calls (three in parallel, then the desk lead): give it a minute.
      signal: AbortSignal.timeout(60_000),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return {
      attempt: previous.attempt + 1,
      fieldErrors: info.fieldErrors,
      error: {
        ...info,
        message: dealDeskErrorText(info.code ?? undefined, info.message),
      },
    };
  }
  redirect(`${back}?done=deal-desk-reviewed#deal-desk`);
}
