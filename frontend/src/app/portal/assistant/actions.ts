"use server";

import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { AssistantConversation } from "@/lib/api-types";
import type { FormState } from "@/lib/form-state";
import { apiFetch } from "@/lib/server/api";

/**
 * Assistant Server Actions. The browser only sends text and IDs; the backend decides
 * everything (whose conversation, what the assistant may read). The API key lives only in the
 * backend.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const MAX = 2000;

export async function sendMessage(
  conversationId: string | null,
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const text = String(formData.get("text") ?? "").trim();
  const attempt = previous.attempt + 1;
  if (!text)
    return {
      attempt,
      values: {},
      fieldErrors: { text: "Type a question first." },
      error: null,
    };
  if (text.length > MAX)
    return {
      attempt,
      values: { text },
      fieldErrors: { text: `At most ${MAX} characters.` },
      error: null,
    };
  if (conversationId !== null && !UUID.test(conversationId))
    throw new Error("invalid conversation id");
  let conversation: AssistantConversation;
  try {
    conversation = await apiFetch<AssistantConversation>(
      "/portal/assistant/messages",
      {
        method: "POST",
        body: JSON.stringify({
          text,
          ...(conversationId ? { conversation_id: conversationId } : {}),
        }),
      },
    );
  } catch (error) {
    const info = toErrorInfo(error);
    return { attempt, values: { text }, fieldErrors: {}, error: info };
  }
  redirect(`/portal/assistant?c=${conversation.id}`);
}

export async function decideAction(
  actionId: string,
  decision: "confirm" | "cancel",
): Promise<void> {
  if (!UUID.test(actionId)) throw new Error("invalid action id");
  const conversation = await apiFetch<AssistantConversation>(
    `/portal/assistant/actions/${actionId}/${decision === "confirm" ? "confirm" : "cancel"}`,
    { method: "POST" },
  );
  redirect(`/portal/assistant?c=${conversation.id}`);
}
