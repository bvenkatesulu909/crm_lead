import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { LeadForm } from "@/components/lead-form";
import { Card, Forbidden, PageHeader } from "@/components/ui";
import { ApiError } from "@/lib/api-error";
import type { Lead } from "@/lib/api-types";
import { leadName } from "@/lib/format";
import { initialLeadFormState } from "@/lib/lead-form-state";
import { availableActions } from "@/lib/lead-rules";
import { apiFetch, getMe } from "@/lib/server/api";

import { updateLead } from "../actions";

export const metadata: Metadata = { title: "Edit lead" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function EditLeadPage({
  params,
}: PageProps<"/leads/[id]/edit">) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  let lead: Lead;
  try {
    lead = await apiFetch<Lead>(`/leads/${id}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    if (error instanceof ApiError && error.status === 403) return <Forbidden />;
    throw error;
  }
  const me = await getMe();
  if (!availableActions(lead, me).edit) {
    return (
      <Forbidden
        message={
          lead.status === "converted"
            ? "A converted lead can no longer be changed."
            : "You can view this lead but not change it."
        }
      />
    );
  }

  const values = {
    first_name: lead.first_name ?? "",
    last_name: lead.last_name,
    company_name: lead.company_name ?? "",
    email: lead.email ?? "",
    phone: lead.phone ?? "",
    job_title: lead.job_title ?? "",
    source: lead.source ?? "",
  };

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link
          href={`/leads/${id}`}
          className="font-medium text-brand-700 hover:underline"
        >
          ← {leadName(lead)}
        </Link>
      </nav>
      <PageHeader
        title="Edit lead"
        description="Status and owner are changed with the buttons on the lead page."
      />
      <Card className="max-w-3xl p-6">
        <LeadForm
          action={updateLead.bind(null, id)}
          initialState={{ ...initialLeadFormState, values }}
          hidden={{ version: String(lead.version) }}
          submitLabel="Save changes"
          pendingLabel="Saving…"
          errorTitle="Your changes could not be saved"
          cancelHref={`/leads/${id}`}
        />
      </Card>
    </>
  );
}
