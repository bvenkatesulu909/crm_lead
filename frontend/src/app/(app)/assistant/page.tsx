import type { Metadata } from "next";

import { StaffAssistantForm } from "./assistant-form";

export const metadata: Metadata = { title: "AI Assistant" };

export default function AssistantPage() {
  return (
    <>
      <h1 className="text-2xl font-semibold tracking-tight text-slate-900">AI Assistant</h1>
      <p className="mt-1 mb-6 text-sm text-slate-600">
        Ask anything about your CRM data. The assistant finds relevant records from the modules you
        can access, enforces permissions on every lookup, and never sends anything automatically.
      </p>
      <StaffAssistantForm />
    </>
  );
}