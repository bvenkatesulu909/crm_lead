"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type {
  CustomAgent,
  CustomAgentRun,
  CustomAgentTrial,
} from "@/lib/api-types";
import { isUuid } from "@/lib/communications";
import {
  AGENT_KEY,
  customAgentErrorText,
  definitionFromForm,
  definitionToValues,
  type RunState,
  type TrialState,
} from "@/lib/custom-agents";
import type { DialogState } from "@/lib/dialog-state";
import type { FormState } from "@/lib/form-state";
import { apiFetch } from "@/lib/server/api";

/**
 * Server Actions of the custom agent builder (ADR 0034). Every id and version comes from the
 * browser, so they are untrusted - that is fine: the API checks that the person may define, try
 * or run agents, that the agent and the record exist and may be read, and that the version is
 * current. The organisation and the person are never sent, and nothing here decides what an agent
 * may read or suggest: the API only accepts the fixed menus. This code reads the forms and turns
 * the API's codes into plain words.
 */

const LIST = "/automation/custom-agents";

function error(previous: { attempt: number }, caught: unknown) {
  const info = toErrorInfo(caught);
  return {
    attempt: previous.attempt + 1,
    fieldErrors: info.fieldErrors,
    error: {
      ...info,
      message: customAgentErrorText(info.code ?? undefined, info.message),
    },
  };
}

function agentPath(id: string): string {
  if (!isUuid(id)) throw new Error("invalid agent");
  return `${LIST}/${id}`;
}

export async function createCustomAgent(
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const definition = definitionFromForm(formData);
  let created: CustomAgent;
  try {
    created = await apiFetch<CustomAgent>("/custom-agents", {
      method: "POST",
      body: JSON.stringify(definition),
    });
  } catch (caught) {
    return {
      ...error(previous, caught),
      values: definitionToValues(definition),
    };
  }
  redirect(`${agentPath(created.id)}?done=created`);
}

export async function updateCustomAgent(
  agentId: string,
  version: number,
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const back = agentPath(agentId); // throws for a tampered id
  const definition = definitionFromForm(formData);
  try {
    await apiFetch<CustomAgent>(`/custom-agents/${agentId}`, {
      method: "PUT",
      body: JSON.stringify({ ...definition, version }),
    });
  } catch (caught) {
    return {
      ...error(previous, caught),
      values: definitionToValues(definition),
    };
  }
  redirect(`${back}?done=saved`);
}

export async function archiveCustomAgent(
  agentId: string,
  previous: DialogState,
): Promise<DialogState> {
  agentPath(agentId);
  try {
    await apiFetch(`/custom-agents/${agentId}/archive`, { method: "POST" });
  } catch (caught) {
    return error(previous, caught);
  }
  redirect(`${LIST}?done=archived`);
}

export async function tryCustomAgent(
  agentId: string,
  previous: TrialState,
  formData: FormData,
): Promise<TrialState> {
  agentPath(agentId);
  const recordId = String(formData.get("record_id") ?? "");
  const values = { record_id: recordId };
  if (!isUuid(recordId))
    return {
      ...previous,
      attempt: previous.attempt + 1,
      values,
      trial: null,
      error: null,
      fieldErrors: { record_id: "Choose a record to try the agent on." },
    };
  try {
    const trial = await apiFetch<CustomAgentTrial>(
      `/custom-agents/${agentId}/try`,
      {
        method: "POST",
        body: JSON.stringify({ record_id: recordId }),
        // An AI model can take longer than the default 10 s API timeout (free models often do).
        signal: AbortSignal.timeout(60_000),
      },
    );
    return {
      attempt: previous.attempt + 1,
      fieldErrors: {},
      error: null,
      trial,
      values,
    };
  } catch (caught) {
    return { ...error(previous, caught), trial: null, values };
  }
}

/** Switch a custom agent on or off in the AI agents registry. The registry refuses to switch an
 * agent on before its current version had a dry run. */
export async function switchCustomAgent(
  agentId: string,
  agentKey: string,
  registryVersion: number | null,
  enable: boolean,
  previous: DialogState,
): Promise<DialogState> {
  const back = agentPath(agentId);
  if (!AGENT_KEY.test(agentKey)) throw new Error("invalid agent");
  try {
    await apiFetch(`/agents/${agentKey}`, {
      method: "PATCH",
      body: JSON.stringify({
        ...(registryVersion === null ? {} : { version: registryVersion }),
        enabled: enable,
      }),
    });
  } catch (caught) {
    return error(previous, caught);
  }
  redirect(`${back}?done=${enable ? "on" : "off"}`);
}

/** Run an agent on one record (sales staff). The result is shown on the record's page: at most
 * one proposal that a different person approves. */
export async function runCustomAgent(
  agentId: string,
  recordId: string,
  previous: RunState,
): Promise<RunState> {
  agentPath(agentId);
  if (!isUuid(recordId)) throw new Error("invalid record");
  try {
    const result = await apiFetch<CustomAgentRun>(
      `/custom-agents/${agentId}/runs`,
      {
        method: "POST",
        body: JSON.stringify({ record_id: recordId }),
        signal: AbortSignal.timeout(60_000),
      },
    );
    return { attempt: previous.attempt + 1, error: null, result };
  } catch (caught) {
    const failed = error(previous, caught);
    return { attempt: failed.attempt, error: failed.error, result: null };
  }
}
