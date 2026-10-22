import type { Metadata } from "next";
import Link from "next/link";

import { KnowledgeAsk } from "@/components/knowledge-ask";
import { Card } from "@/components/ui";

import { askPortalKnowledge, submitPortalFeedback } from "./actions";

export const metadata: Metadata = { title: "Help & policies" };

/** Customer help: answers only from knowledge shared with this customer's accounts. */
export default function PortalKnowledgePage() {
  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link href="/portal" className="font-medium text-brand-700 hover:underline">
          ← Portal home
        </Link>
      </nav>
      <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
        Help &amp; policies
      </h1>
      <p className="mt-1 mb-6 text-sm text-slate-600">
        Ask about returns, delivery, payments or product care. Answers use only documents shared
        with your company, and every answer shows the passages it used.
      </p>
      <div className="grid gap-6 lg:grid-cols-[1fr_18rem]">
        <Card className="p-5">
          <KnowledgeAsk action={askPortalKnowledge} feedbackAction={submitPortalFeedback} />
        </Card>
        <Card className="p-5 text-sm text-slate-600">
          <h2 className="text-base font-semibold text-slate-900">How this works</h2>
          <ul className="mt-2 list-disc space-y-2 pl-4">
            <li>You see public help and documents for the accounts in your portal access.</li>
            <li>Internal staff documents are never used.</li>
            <li>If nothing relevant is found, the assistant says so instead of guessing.</li>
          </ul>
        </Card>
      </div>
    </>
  );
}