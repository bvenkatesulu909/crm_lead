"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import { accountPath, researchErrorText } from "@/lib/deal-desk";
import type { DialogState } from "@/lib/dialog-state";
import { apiFetch } from "@/lib/server/api";

/**
 * Server Action of account research (ADR 0024). The account id comes from the browser, so it is
 * untrusted - the API checks that the person may read the account. Nothing else is sent.
 */
export async function researchAccount(
  accountId: string,
  previous: DialogState,
): Promise<DialogState> {
  const back = accountPath(accountId); // throws for a tampered id
  try {
    await apiFetch("/account-research/briefs", {
      method: "POST",
      body: JSON.stringify({ account_id: accountId }),
      // One model call over the gathered facts; give it a minute like the other AI calls.
      signal: AbortSignal.timeout(60_000),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return {
      attempt: previous.attempt + 1,
      fieldErrors: info.fieldErrors,
      error: {
        ...info,
        message: researchErrorText(info.code ?? undefined, info.message),
      },
    };
  }
  redirect(`${back}?done=account-researched#account-research`);
}
