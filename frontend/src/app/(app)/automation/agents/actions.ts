"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { Agent } from "@/lib/api-types";
import { agentErrorText, parseBudget, toggledTools } from "@/lib/agents";
import type { FormState } from "@/lib/form-state";
import { apiFetch } from "@/lib/server/api";

/**
 * Server Action of the AI agents page (ADR 0016). The agent key, the tool names and the version
 * come from the browser, so they are untrusted - that is fine: the API checks that this user
 * is a tenant admin, that the agent exists, that every tool belongs to it and that the version
 * is current. This code only reads the form and adds no permission logic of its own.
 */

const KEY = /^[a-z][a-z_]{2,39}$/;

export async function updateAgent(
  key: string,
  version: number | null,
  allTools: string[],
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  if (!KEY.test(key)) throw new Error("invalid agent");
  const attempt = previous.attempt + 1;
  const tools = formData.getAll("tools").map(String);
  const values = {
    enabled: formData.get("enabled") === "on" ? "on" : "off",
    budget: String(formData.get("budget") ?? ""),
    tools_chosen: tools.join(","),
  };
  const budget = parseBudget(values.budget);
  if ("error" in budget)
    return {
      attempt,
      values,
      fieldErrors: { budget: budget.error },
      error: null,
    };
  try {
    await apiFetch<Agent>(`/agents/${key}`, {
      method: "PATCH",
      body: JSON.stringify({
        ...(version === null ? {} : { version }),
        enabled: values.enabled === "on",
        monthly_token_budget: budget.value,
        allowed_tools: toggledTools(tools, allTools),
      }),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return {
      attempt,
      values,
      fieldErrors: info.fieldErrors,
      error: {
        ...info,
        message: agentErrorText(info.code ?? undefined, info.message),
      },
    };
  }
  redirect(`/automation/agents?done=${key}#agent-${key}`);
}
