"use client";

import { useActionState } from "react";

import { ErrorAlert, buttonClass } from "@/components/ui";
import type { KnowledgeDraftState } from "@/app/(app)/tickets/actions";

const initial: KnowledgeDraftState = { attempt: 0, draft: null, sources: [], error: null };

/** Generate a customer-scoped reply draft from the knowledge base; nothing is sent. */
export function KnowledgeDraftButton({
  action,
}: {
  action: (state: KnowledgeDraftState, formData: FormData) => Promise<KnowledgeDraftState>;
}) {
  const [state, formAction, pending] = useActionState(action, initial);
  return (
    <div className="border-t border-slate-200 px-5 py-4 text-sm">
      <form action={formAction}>
        <button type="submit" disabled={pending} className={buttonClass("secondary")}>
          {pending ? "Drafting…" : "Draft reply from knowledge base"}
        </button>
      </form>
      {state.error && <div className="mt-3"><ErrorAlert title="Draft unavailable" error={state.error} /></div>}
      {state.draft && (
        <div className="mt-3 rounded-md bg-slate-50 p-3 ring-1 ring-slate-200">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Draft (customer-visible sources only)
          </p>
          <p className="mt-1 whitespace-pre-line text-slate-800">{state.draft}</p>
          {state.sources.length > 0 && (
            <ul className="mt-2 space-y-1 border-t border-slate-200 pt-2 text-xs text-slate-600">
              {state.sources.map((source, index) => (
                <li key={`${source.document_title}-${index}`}>
                  [${index + 1}] {source.document_title}
                  {source.heading_path ? ` - ${source.heading_path}` : ""}
                  {source.page_from !== null ? ` (p. ${source.page_from})` : ""}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
