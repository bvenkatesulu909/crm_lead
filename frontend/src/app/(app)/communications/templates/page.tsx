import type { Metadata } from "next";
import Link from "next/link";

import { TemplateActiveDialog } from "@/components/template-dialogs";
import {
  ButtonLink,
  Card,
  EmptyState,
  ErrorAlert,
  Forbidden,
  PageHeader,
  SuccessAlert,
} from "@/components/ui";
import { ApiError, toErrorInfo } from "@/lib/api-error";
import type { EmailTemplate } from "@/lib/api-types";
import { formatDateTime } from "@/lib/format";
import { canManageEmailTemplates } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import { setTemplateActive } from "../actions";

export const metadata: Metadata = { title: "E-mail templates" };

const DONE: Record<string, string> = {
  created: "The template was created.",
  updated: "Your changes were saved.",
  deactivated: "The template was deactivated. Agents no longer see it.",
  reactivated: "The template is active again.",
};

/** Templates for one-to-one e-mails (managers and tenant admins). Agents use the active ones. */
export default async function TemplatesPage({
  searchParams,
}: PageProps<"/communications/templates">) {
  const query = await searchParams;
  const done = typeof query.done === "string" ? DONE[query.done] : undefined;
  const me = await getMe();
  if (!canManageEmailTemplates(me)) return <Forbidden />;

  let templates: EmailTemplate[];
  try {
    templates = await apiFetch<EmailTemplate[]>("/communications/templates?include_inactive=true");
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) return <Forbidden />;
    return <ErrorAlert title="Templates could not be loaded" error={toErrorInfo(error)} />;
  }

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link href="/communications" className="font-medium text-brand-700 hover:underline">← Communication Center</Link>
      </nav>
      <PageHeader
        title="E-mail templates"
        description="Ready-made texts your team can start from when writing to a lead or contact."
        actions={<ButtonLink href="/communications/templates/new">New template</ButtonLink>}
      />
      {done && <div className="mb-4"><SuccessAlert>{done}</SuccessAlert></div>}
      <Card>
        {templates.length === 0 ? (
          <EmptyState title="No templates yet" description="Create one for the e-mails your team writes most often, such as a first reply." />
        ) : (
          <ul className="divide-y divide-slate-100">
            {templates.map((t) => (
              <li key={t.id} className="flex flex-wrap items-start justify-between gap-3 px-5 py-4">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <Link href={`/communications/templates/${t.id}`} className="font-medium text-brand-700 hover:underline">{t.name}</Link>
                    {!t.is_active && <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-700 ring-1 ring-inset ring-slate-300">Inactive</span>}
                  </div>
                  <p className="mt-0.5 break-words text-sm text-slate-700">{t.subject}</p>
                  <p className="text-xs text-slate-500">Changed {formatDateTime(t.updated_at)}</p>
                </div>
                <div className="flex gap-2">
                  <ButtonLink href={`/communications/templates/${t.id}`} variant="secondary">Edit</ButtonLink>
                  <TemplateActiveDialog action={setTemplateActive.bind(null, t.id, t.version, !t.is_active)} name={t.name} active={t.is_active} />
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  ); // prettier-ignore
}
