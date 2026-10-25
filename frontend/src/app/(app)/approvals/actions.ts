"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { AgentAction } from "@/lib/api-types";
import { checkDecisionNote, decisionErrorText } from "@/lib/approvals";
import type { DialogState } from "@/lib/dialog-state";
import { apiFetch } from "@/lib/server/api";

/**
 * Server Actions of the approval queue (ADR 0014). The proposal id and version come from the
 * browser, so they are untrusted - that is fine: the API checks that this user may decide, that
 * the proposal is someone else's, still waiting and unchanged, and that they can see the
 * record. This code adds no permission logic of its own.
 */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function proposalPath(id: string): string {
  if (!UUID.test(id)) throw new Error("invalid proposal id");
  return `/approvals/${id}`;
}

async function decide(
  id: string,
  version: number,
  decision: "approve" | "reject",
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const path = proposalPath(id);
  const note = String(formData.get("note") ?? "");
  const problem = checkDecisionNote(note, decision === "reject");
  if (problem)
    return {
      attempt: previous.attempt + 1,
      fieldErrors: { note: problem },
      error: null,
    };
  try {
    await apiFetch<AgentAction>(`/approvals/actions/${id}/${decision}`, {
      method: "POST",
      body: JSON.stringify({ version, note: note.trim() || null }),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return {
      attempt: previous.attempt + 1,
      fieldErrors: info.fieldErrors,
      error: {
        ...info,
        message: decisionErrorText(info.code ?? undefined, info.message),
      },
    };
  }
  redirect(`${path}?done=${decision === "approve" ? "approved" : "rejected"}`);
}

export async function approveProposal(
  id: string,
  version: number,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  return decide(id, version, "approve", previous, formData);
}

export async function rejectProposal(
  id: string,
  version: number,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  return decide(id, version, "reject", previous, formData);
}
