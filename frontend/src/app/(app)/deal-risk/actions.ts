"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import {
  coachErrorText,
  dealRiskErrorText,
  opportunityPath,
  type CoachState,
  type DealRiskCoach,
} from "@/lib/deal-risk";
import type { DialogState } from "@/lib/dialog-state";
import { apiFetch } from "@/lib/server/api";

/**
 * Server Action of the deal risk forecast (ADR 0037). The deal id comes from the browser, so it is
 * untrusted - that is fine: the API checks that the person may see deal risk and may read the
 * deal. Nothing else is sent (no level, no score: the server works them out). This code only turns
 * the API's codes into plain words and goes back to the deal.
 */
export async function updateDealRisk(
  opportunityId: string,
  previous: DialogState,
): Promise<DialogState> {
  const back = opportunityPath(opportunityId); // throws for a tampered id
  try {
    await apiFetch(`/deal-risk/${opportunityId}/recompute`, { method: "POST" });
  } catch (error) {
    const info = toErrorInfo(error);
    return {
      attempt: previous.attempt + 1,
      fieldErrors: info.fieldErrors,
      error: {
        ...info,
        message: dealRiskErrorText(info.code ?? undefined, info.message),
      },
    };
  }
  redirect(`${back}?done=deal-risk-updated#deal-risk`);
}

/**
 * Asks the optional AI coach about a deal's forecast (ADR 0037, DR5). Only the deal id is sent; the
 * API checks the person, the deal and the coach's switch. The advice is not stored, so it comes
 * back to the screen instead of reloading the page. Any task it suggests only waits in the
 * approval queue.
 */
export async function askDealRiskCoach(
  opportunityId: string,
  previous: CoachState,
): Promise<CoachState> {
  opportunityPath(opportunityId); // throws for a tampered id
  try {
    const result = await apiFetch<DealRiskCoach>(
      `/deal-risk/${opportunityId}/coach`,
      { method: "POST", signal: AbortSignal.timeout(60_000) },
    );
    return { attempt: previous.attempt + 1, result, error: null };
  } catch (error) {
    const info = toErrorInfo(error);
    return {
      attempt: previous.attempt + 1,
      result: null,
      error: {
        ...info,
        message: coachErrorText(info.code ?? undefined, info.message),
      },
    };
  }
}
