import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { TemplateForm } from "@/components/template-form";
import { Forbidden, PageHeader } from "@/components/ui";
import { ApiError } from "@/lib/api-error";
import type { EmailTemplate, Placeholder } from "@/lib/api-types";
import { isUuid } from "@/lib/communications";
import { initialFormState } from "@/lib/form-state";
import { canManageEmailTemplates } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import { updateTemplate } from "../../actions";

export const metadata: Metadata = { title: "Edit e-mail template" };

async function loadTemplate(id: string): Promise<EmailTemplate | "forbidden"> {
  if (!isUuid(id)) notFound();
  try {
    return await apiFetch<EmailTemplate>(`/communications/templates/${id}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    if (error instanceof ApiError && error.status === 403) return "forbidden";
    throw error;
  }
}

export default async function EditTemplatePage({
  params,
}: PageProps<"/communications/templates/[id]">) {
  const { id } = await params;
  const me = await getMe();
  if (!canManageEmailTemplates(me)) return <Forbidden />;
  const [template, placeholders] = await Promise.all([
    loadTemplate(id),
    apiFetch<Placeholder[]>("/communications/placeholders"),
  ]);
  if (template === "forbidden") return <Forbidden />;

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link href="/communications/templates" className="font-medium text-brand-700 hover:underline">← E-mail templates</Link>
      </nav>
      <PageHeader
        title={`Edit ${template.name}`}
        description={template.is_active ? undefined : "This template is inactive: agents don't see it."}
      />
      <TemplateForm
        action={updateTemplate.bind(null, template.id, template.version)}
        initialState={initialFormState}
        template={template}
        placeholders={placeholders}
        submitLabel="Save changes"
      />
    </>
  ); // prettier-ignore
}
