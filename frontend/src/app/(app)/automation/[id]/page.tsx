import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { RuleForm } from "@/components/rule-form";
import { Card, Forbidden, PageHeader } from "@/components/ui";
import { ApiError } from "@/lib/api-error";
import type {
  DirectoryUser,
  WorkflowCatalogue,
  WorkflowRule,
} from "@/lib/api-types";
import { initialFormState } from "@/lib/form-state";
import { canManageWorkflows } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import { deleteRule, updateRule } from "../actions";
import { DeleteRuleButton } from "../delete-rule";

export const metadata: Metadata = { title: "Automation rule" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function EditRulePage({
  params,
}: PageProps<"/automation/[id]">) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  const me = await getMe();
  if (!canManageWorkflows(me)) return <Forbidden />;
  let rule: WorkflowRule;
  try {
    rule = await apiFetch<WorkflowRule>(`/workflows/rules/${id}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
  const [catalogue, people] = await Promise.all([
    apiFetch<WorkflowCatalogue>("/workflows/catalogue"),
    apiFetch<DirectoryUser[]>("/users").catch(() => []),
  ]);
  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link href="/automation" className="font-medium text-brand-700 hover:underline">← Automation</Link>
      </nav>
      <PageHeader title={rule.name} description="Changes apply to what happens from now on."
        actions={<DeleteRuleButton action={deleteRule.bind(null, rule.id)} name={rule.name} />} />
      <Card className="p-6">
        <RuleForm key={rule.version} action={updateRule.bind(null, rule.id, rule.version)} initialState={initialFormState}
          catalogue={catalogue} colleagues={people.map((p) => ({ id: p.id, name: p.display_name }))} rule={rule} submitLabel="Save rule" />
      </Card>
    </>
  ); // prettier-ignore
}
