"use server";

import { toErrorInfo } from "@/lib/api-error";
import {
  checkPositions,
  isVersionNumber,
  notesErrorText,
  type NotesDraft,
  type NotesPage,
  type ProposalOutcome,
  type ProposalPreview,
} from "@/lib/call-notes";
import { isUuid } from "@/lib/communications";
import { apiFetch } from "@/lib/server/api";

import type { Fetched } from "./call-actions";

/**
 * Call notes Server Actions (ADR 0035). The lead and call ids come from the page and are checked
 * here; the API decides who may read the lead and applies every rule again. What is sent is built
 * from a short list of fields: asking for notes sends NOTHING (the API knows the lead, the call and
 * the organisation's frame), asking for suggestions sends only the chosen line numbers and whether
 * to add the follow-up task - never a key, a value, a status or an id of anything else.
 */

const base = (leadId: string, callId: string) => {
  if (!isUuid(leadId)) throw new Error("invalid lead");
  if (!isUuid(callId)) throw new Error("invalid recording");
  return `/leads/${leadId}/calls/${callId}/notes`;
};

function problem(error: unknown): { ok: false; message: string } {
  const info = toErrorInfo(error);
  return { ok: false, message: notesErrorText(info.code, info.message) };
}

function versionPath(path: string, version: unknown): string {
  if (!isVersionNumber(version)) throw new Error("invalid version");
  return `${path}/${version}`;
}

export async function readNotes(
  leadId: string,
  callId: string,
): Promise<Fetched<NotesPage>> {
  const path = base(leadId, callId);
  try {
    return { ok: true, value: await apiFetch<NotesPage>(path) };
  } catch (error) {
    return problem(error);
  }
}

export async function readNotesVersion(
  leadId: string,
  callId: string,
  version: number,
): Promise<Fetched<NotesDraft>> {
  const path = versionPath(base(leadId, callId), version);
  try {
    return { ok: true, value: await apiFetch<NotesDraft>(path) };
  } catch (error) {
    return problem(error);
  }
}

/** No body: the lead, the call and the frame are the server's. */
export async function createNotes(
  leadId: string,
  callId: string,
): Promise<Fetched<NotesDraft>> {
  const path = base(leadId, callId);
  try {
    return {
      ok: true,
      value: await apiFetch<NotesDraft>(path, { method: "POST" }),
    };
  } catch (error) {
    return problem(error);
  }
}

export type ProposalChoice = {
  positions: number[] | null;
  followUpTask: boolean;
};

/** What asking would suggest for the WHOLE draft; the person unticks what they do not want. */
export async function previewProposals(
  leadId: string,
  callId: string,
  version: number,
  followUpTask: boolean,
): Promise<Fetched<ProposalPreview>> {
  const path = versionPath(base(leadId, callId), version);
  try {
    return {
      ok: true,
      value: await apiFetch<ProposalPreview>(
        `${path}/proposals/preview?follow_up_task=${followUpTask === false ? "false" : "true"}`,
      ),
    };
  } catch (error) {
    return problem(error);
  }
}

export async function makeProposals(
  leadId: string,
  callId: string,
  version: number,
  choice: ProposalChoice,
): Promise<Fetched<ProposalOutcome[]>> {
  const path = versionPath(base(leadId, callId), version);
  const positions = checkPositions(choice?.positions);
  if (!positions.ok) return positions;
  try {
    const done = await apiFetch<{ items: ProposalOutcome[] }>(
      `${path}/proposals`,
      {
        method: "POST",
        body: JSON.stringify({
          positions: positions.value,
          follow_up_task: choice?.followUpTask !== false,
        }),
      },
    );
    return { ok: true, value: done.items };
  } catch (error) {
    return problem(error);
  }
}
