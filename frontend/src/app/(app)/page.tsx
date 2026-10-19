import type { Metadata } from "next";
import Link from "next/link";

import {
  ButtonLink,
  Card,
  EmptyState,
  ErrorAlert,
  PageHeader,
  StatusBadge,
} from "@/components/ui";
import { toErrorInfo } from "@/lib/api-error";
import type {
  Dashboard,
  DirectoryUser,
  LeadPage,
  LeadStatus,
  Me,
} from "@/lib/api-types";
import {
  ActivityFeed,
  ExecutiveTiles,
  FilterBar,
  FollowUpList,
  LeadFunnel,
  PipelineByStage,
  SalesTiles,
  TeamTable,
  ViewTabs,
} from "@/components/dashboard";
import {
  dashboardQuery,
  hasDashboard,
  parseDashboardFilters,
  type DashboardFilters,
} from "@/lib/dashboard";
import { canReadLeads, canWriteLeads } from "@/lib/permissions";
import { ModuleGrid } from "@/components/module-grid";
import { modulesFor } from "@/lib/modules";
import { apiFetch, getMe } from "@/lib/server/api";
import { formatDate, leadName } from "@/lib/format";

export const metadata: Metadata = { title: "Dashboard" };

const TILES: { label: string; status?: LeadStatus }[] = [
  { label: "All leads" },
  { label: "New", status: "new" },
  { label: "Qualified", status: "qualified" },
  { label: "Converted", status: "converted" },
];

async function leadTotals() {
  // `total` respects the user's scope: agents see counts of THEIR leads only.
  return Promise.all(
    TILES.map(async (tile) => {
      const query = new URLSearchParams({
        limit: "1",
        ...(tile.status && { status: tile.status }),
      });
      return {
        ...tile,
        total: (await apiFetch<LeadPage>(`/leads?${query}`)).total,
      };
    }),
  );
}

async function LeadOverview({ me }: { me: Me }) {
  let totals: Awaited<ReturnType<typeof leadTotals>>;
  let recent: LeadPage;
  try {
    [totals, recent] = await Promise.all([
      leadTotals(),
      apiFetch<LeadPage>("/leads?limit=5&sort=-created_at"),
    ]);
  } catch (error) {
    return (
      <ErrorAlert
        title="Lead figures are unavailable"
        error={toErrorInfo(error)}
      />
    );
  }
  return (
    <>
      <dl className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {totals.map((tile) => (
          <Card key={tile.label} className="p-5">
            <dt className="text-sm font-medium text-slate-600">{tile.label}</dt>
            <dd className="mt-2 text-3xl font-semibold tracking-tight text-slate-900">
              <Link
                href={tile.status ? `/leads?status=${tile.status}` : "/leads"}
                className="hover:text-brand-700"
                aria-label={`${tile.label}: ${tile.total}. View leads`}
              >
                {tile.total}
              </Link>
            </dd>
          </Card>
        ))}
      </dl>

      <Card className="mt-6">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <h2 className="text-base font-semibold text-slate-900">
            Recent leads
          </h2>
          <Link
            href="/leads"
            className="text-sm font-medium text-brand-700 hover:underline"
          >
            View all
          </Link>
        </div>
        {recent.items.length === 0 ? (
          <EmptyState
            title="No leads yet"
            description="Leads you create or are assigned will appear here."
            action={
              canWriteLeads(me) && (
                <ButtonLink href="/leads/new">Create a lead</ButtonLink>
              )
            }
          />
        ) : (
          <ul className="divide-y divide-slate-100">
            {recent.items.map((lead) => (
              <li
                key={lead.id}
                className="flex items-center justify-between gap-4 px-5 py-3"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-slate-900">
                    <Link
                      href={`/leads/${lead.id}`}
                      className="hover:text-brand-700 hover:underline"
                    >
                      {leadName(lead)}
                    </Link>
                  </p>
                  <p className="truncate text-xs text-slate-500">
                    {lead.company_name ?? "No company"} ·{" "}
                    {formatDate(lead.created_at)}
                  </p>
                </div>
                <StatusBadge status={lead.status} />
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}

async function RoleDashboard({ filters }: { filters: DashboardFilters }) {
  let data: Dashboard;
  try {
    data = await apiFetch<Dashboard>(`/dashboard?${dashboardQuery(filters)}`);
  } catch (error) {
    return (
      <ErrorAlert
        title="Dashboard figures are unavailable"
        error={toErrorInfo(error)}
      />
    );
  }
  // The rep list only feeds the filter; without it the dashboard still works.
  const reps =
    data.view === "representative"
      ? null
      : await apiFetch<DirectoryUser[]>("/users?assignable=true").catch(
          () => null,
        );
  return (
    <div data-testid={`dashboard-${data.view}`}>
      <ViewTabs
        views={data.available_views}
        current={data.view}
        filters={filters}
      />
      <FilterBar filters={filters} view={data.view} reps={reps} />
      <ExecutiveTiles data={data} />
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
        {data.view === "representative" ? "My sales" : "Sales"}
      </h2>
      <SalesTiles data={data} />
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <LeadFunnel data={data} />
        <PipelineByStage data={data} />
        <FollowUpList data={data} />
        <ActivityFeed data={data} />
      </div>
      {data.team && (
        <div className="mt-6">
          <TeamTable data={data} filters={filters} />
        </div>
      )}
    </div>
  );
}

export default async function DashboardPage({ searchParams }: PageProps<"/">) {
  const me = await getMe();
  const firstName = (me.display_name ?? "").split(" ")[0];

  return (
    <>
      <PageHeader
        title={firstName ? `Welcome back, ${firstName}` : "Welcome"}
        description="Here is what's happening in your CRM."
        actions={
          canWriteLeads(me) && (
            <ButtonLink href="/leads/new">New lead</ButtonLink>
          )
        }
      />
      {hasDashboard(me) ? (
        <RoleDashboard
          filters={parseDashboardFilters(await searchParams, new Date())}
        />
      ) : canReadLeads(me) ? (
        <LeadOverview me={me} />
      ) : (
        <Card className="p-6">
          <EmptyState
            title={
              me.user_type === "platform"
                ? "Platform administration"
                : "Nothing to show yet"
            }
            description={
              me.user_type === "platform"
                ? "You are signed in as a platform administrator. Tenant business data is not visible to this role."
                : "Your role has no sales screens yet. The modules below show what is available and what is coming."
            }
          />
        </Card>
      )}
      {/* Tenant staff see the module overview; platform admins have no tenant modules. */}
      {me.user_type === "staff" && <ModuleGrid modules={modulesFor(me)} />}
    </>
  );
}
