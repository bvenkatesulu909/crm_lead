import type { Metadata } from "next";

import { Card, Forbidden, PageHeader, SuccessAlert } from "@/components/ui";
import type { TenantSummary } from "@/lib/api-types";
import { hasAny } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import { createOrganisation } from "./actions";
import { CreateOrganisationButton } from "./create-organisation";

export const metadata: Metadata = { title: "Organisations" };

/** Super Admin only: the organisations on this platform (names only - no business data). */
export default async function PlatformPage({
  searchParams,
}: PageProps<"/platform">) {
  const [me, query] = await Promise.all([getMe(), searchParams]);
  if (!hasAny(me, "platform:tenant:read")) return <Forbidden />;
  const tenants = await apiFetch<TenantSummary[]>("/platform/tenants");
  const manage = hasAny(me, "platform:tenant:manage");

  return (
    <>
      <PageHeader
        title="Organisations"
        description="Companies using this CRM. Each one manages its own users and data."
        actions={
          manage && <CreateOrganisationButton action={createOrganisation} />
        }
      />
      {query.done === "created" && (
        <div className="mb-4">
          <SuccessAlert>
            The organisation was created. Its first admin received an invitation
            e-mail.
          </SuccessAlert>
        </div>
      )}
      <Card>
        <ul className="divide-y divide-slate-100">
          {tenants.map((t) => (
            <li
              key={t.id}
              className="flex items-center justify-between gap-3 px-5 py-3"
            >
              <div>
                <p className="font-medium text-slate-900">{t.name}</p>
                <p className="font-mono text-xs text-slate-500">{t.slug}</p>
              </div>
              <span className="text-xs text-slate-600">{t.status}</span>
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}
