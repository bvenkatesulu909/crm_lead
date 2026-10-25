import type { Metadata } from "next";
import Link from "next/link";

import { TemplateForm } from "@/components/template-form";
import { Forbidden, PageHeader } from "@/components/ui";
import type { Placeholder } from "@/lib/api-types";
import { initialFormState } from "@/lib/form-state";
import { canManageEmailTemplates } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import { createTemplate } from "../../actions";

export const metadata: Metadata = { title: "New e-mail template" };

export default async function NewTemplatePage() {
  const me = await getMe();
  if (!canManageEmailTemplates(me)) return <Forbidden />;
  const placeholders = await apiFetch<Placeholder[]>("/communications/placeholders");

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link href="/communications/templates" className="font-medium text-brand-700 hover:underline">← E-mail templates</Link>
      </nav>
      <PageHeader title="New e-mail template" />
      <TemplateForm action={createTemplate} initialState={initialFormState} placeholders={placeholders} submitLabel="Create template" />
    </>
  ); // prettier-ignore
}
