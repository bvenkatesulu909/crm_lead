import type { Metadata } from "next";
import Link from "next/link";

import { Pagination } from "@/components/pagination";
import {
  ButtonLink,
  Card,
  EmptyState,
  ErrorAlert,
  Forbidden,
  PageHeader,
  StatusBadge,
  SuccessAlert,
} from "@/components/ui";
import { ApiError, toErrorInfo } from "@/lib/api-error";
import { ScoreBadge } from "@/components/lead-score";
import { LEAD_SORTS, type LeadPage } from "@/lib/api-types";
import { SOURCE_LABELS, formatDate, leadName } from "@/lib/format";
import { canWriteLeads } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import { LeadFilters } from "./lead-filters";
import {
  PAGE_SIZE,
  apiQuery,
  hasFilters,
  pageHref,
  parseListParams,
} from "./list-params";

export const metadata: Metadata = { title: "Leads" };

export default async function LeadsPage({ searchParams }: PageProps<"/leads">) {
  const raw = await searchParams;
  const params = parseListParams(raw);
  const me = await getMe();

  let data: LeadPage;
  try {
    // The backend decides which leads this user may see (own vs. all, own tenant only).
    data = await apiFetch<LeadPage>(`/leads?${apiQuery(params)}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) return <Forbidden />;
    return (
      <>
        <PageHeader title="Leads" />
        <ErrorAlert
          title="Leads could not be loaded"
          error={toErrorInfo(error)}
        />
      </>
    );
  }

  const created = typeof raw.created === "string";
  const canCreate = canWriteLeads(me);

  return (
    <>
      <PageHeader
        title="Leads"
        description={
          me.permissions.includes("lead:read:all")
            ? "All leads of your organisation."
            : "Leads assigned to you."
        }
        actions={
          canCreate && <ButtonLink href="/leads/new">New lead</ButtonLink>
        }
      />

      {created && (
        <div className="mb-4">
          <SuccessAlert>The lead was created.</SuccessAlert>
        </div>
      )}

      <Card>
        <LeadFilters params={params} />
        <div className="border-t border-slate-200">
          {data.items.length === 0 ? (
            hasFilters(params) ? (
              <EmptyState
                title="No leads match your search"
                description="Try other words or remove some filters."
                action={
                  <ButtonLink href="/leads" variant="secondary">
                    Clear filters
                  </ButtonLink>
                }
              />
            ) : (
              <EmptyState
                title="No leads yet"
                description="New leads you create or are assigned to you will appear here."
                action={
                  canCreate && (
                    <ButtonLink href="/leads/new">
                      Create your first lead
                    </ButtonLink>
                  )
                }
              />
            )
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200 text-sm">
                <caption className="sr-only">
                  Leads, page {params.page}, sorted by {LEAD_SORTS[params.sort]}
                </caption>
                <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-600">
                  <tr>
                    <th scope="col" className="px-5 py-3">
                      Name
                    </th>
                    <th scope="col" className="px-5 py-3">
                      Company
                    </th>
                    <th scope="col" className="hidden px-5 py-3 md:table-cell">
                      E-mail
                    </th>
                    <th scope="col" className="px-5 py-3">
                      Status
                    </th>
                    <th scope="col" className="px-5 py-3">
                      Score
                    </th>
                    <th scope="col" className="hidden px-5 py-3 lg:table-cell">
                      Source
                    </th>
                    <th scope="col" className="hidden px-5 py-3 sm:table-cell">
                      Created
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {data.items.map((lead) => (
                    <tr key={lead.id} className="hover:bg-slate-50">
                      <th
                        scope="row"
                        className="text-left whitespace-nowrap px-5 py-3 font-medium text-slate-900"
                      >
                        <Link
                          href={`/leads/${lead.id}`}
                          className="text-brand-700 hover:underline"
                        >
                          {leadName(lead)}
                        </Link>
                      </th>
                      <td className="px-5 py-3 text-slate-700">
                        {lead.company_name ?? "—"}
                      </td>
                      <td className="hidden px-5 py-3 text-slate-700 md:table-cell">
                        {lead.email ?? "—"}
                      </td>
                      <td className="px-5 py-3">
                        <StatusBadge status={lead.status} />
                      </td>
                      <td className="px-5 py-3">
                        <ScoreBadge
                          score={lead.score}
                          priority={lead.priority}
                        />
                      </td>
                      <td className="hidden px-5 py-3 text-slate-700 lg:table-cell">
                        {lead.source ? SOURCE_LABELS[lead.source] : "—"}
                      </td>
                      <td className="hidden whitespace-nowrap px-5 py-3 text-slate-700 sm:table-cell">
                        {formatDate(lead.created_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        {data.total > 0 && (
          <div className="border-t border-slate-200">
            <Pagination
              total={data.total}
              page={params.page}
              pageSize={PAGE_SIZE}
              hrefForPage={(page) => pageHref(params, page)}
            />
          </div>
        )}
      </Card>
    </>
  );
}
