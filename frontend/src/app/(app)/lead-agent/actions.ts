"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { DialogState } from "@/lib/dialog-state";
import { leadAgentErrorText, outcomeDone } from "@/lib/lead-agent";
import { leadPath } from "@/lib/qualifier";
import { apiFetch } from "@/lib/server/api";

/**
 * Server Action of the lead agent (ADR 0022). The lead id comes from the browser, so it is
 * untrusted - that is fine: the API checks that the person may read the lead and may use the
 * agent. The organisation and the person are never sent. This code only turns the API's codes
 * into plain words and goes back to the lead.
 */
export async function askLeadAgent(
  leadId: string,
  previous: DialogState,
): Promise<DialogState> {
  const back = leadPath(leadId); // throws for a tampered id
  let outcome = "no_suggestion";
  try {
    const run = await apiFetch<{ outcome: string }>("/lead-agent/runs", {
      method: "POST",
      body: JSON.stringify({ lead_id: leadId }),
    });
    outcome = run.outcome;
  } catch (error) {
    const info = toErrorInfo(error);
    return {
      attempt: previous.attempt + 1,
      fieldErrors: info.fieldErrors,
      error: {
        ...info,
        message: leadAgentErrorText(info.code ?? undefined, info.message),
      },
    };
  }
  redirect(`${back}?done=${outcomeDone(outcome)}#lead-agent`);
}
