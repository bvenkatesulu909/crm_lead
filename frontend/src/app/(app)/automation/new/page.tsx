import type { Metadata } from "next";
import Link from "next/link";

import { RuleForm } from "@/components/rule-form";
import { Card, Forbidden, PageHeader } from "@/components/ui";
import type { DirectoryUser, WorkflowCatalogue } from "@/lib/api-types";
import { initialFormState } from "@/lib/form-state";
import { canManageWorkflows } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import { createRule } from "../actions";

export const metadata: Metadata = { title: "New automation rule" };

export default async function NewRulePage() {
  const me = await getMe();
  if (!canManageWorkflows(me)) return <Forbidden />;
  const [catalogue, people] = await Promise.all([
    apiFetch<WorkflowCatalogue>("/workflows/catalogue"),
    apiFetch<DirectoryUser[]>("/users").catch(() => []),
  ]);
  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link href="/automation" className="font-medium text-brand-700 hover:underline">← Automation</Link>
      </nav>
      <PageHeader title="New rule" description="Rules act as “Automation” and only inside your organisation. Everything they do appears in the run log and in the record's history." />
      <Card className="p-6">
        <RuleForm action={createRule} initialState={initialFormState} catalogue={catalogue}
          colleagues={people.map((p) => ({ id: p.id, name: p.display_name }))} submitLabel="Create rule" />
      </Card>
    </>
  ); // prettier-ignore
}
