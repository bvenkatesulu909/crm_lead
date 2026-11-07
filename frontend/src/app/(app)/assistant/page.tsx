import type { Metadata } from "next";

import { AssistantConversation } from "@/components/assistant-conversation";
import { apiFetch } from "@/lib/server/api";
import type { VoiceStatus } from "@/lib/voice/choose";

export const metadata: Metadata = { title: "AI Assistant" };

export default async function AssistantPage() {
  // Whether voice is switched on here and which speech engines may be used (ADR 0023). Without
  // an answer the page still works: typing needs no voice.
  const voice = await apiFetch<VoiceStatus>("/voice/status").catch(() => null);
  return (
    <>
      <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
        AI Assistant
      </h1>
      <p className="mt-1 mb-6 text-sm text-slate-600">
        Ask anything about your CRM data. The assistant finds relevant records
        from the modules you can access, enforces permissions on every lookup,
        and never sends anything automatically.
      </p>
      <div className="space-y-6">
        <AssistantConversation voice={voice} />
      </div>
    </>
  );
}
