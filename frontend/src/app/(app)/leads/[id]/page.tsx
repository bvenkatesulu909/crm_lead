import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ActivityPanel } from "@/components/activity-panel";
import { ChatTranscriptCard } from "@/components/chat-transcript-card";
import { EmailCard } from "@/components/email-card";
import { RecordProposals } from "@/components/record-proposals";
import { WebCheckCard } from "@/components/webcheck-card";
import { LeadScoreCard } from "@/components/lead-score";
import { Card, Forbidden, StatusBadge, SuccessAlert } from "@/components/ui";
import { ApiError } from "@/lib/api-error";
import type {
  Account,
  AccountPage,
  Activity,
  Assignment,
  DirectoryUser,
  Lead,
  LeadScore,
  PublicChatTranscript,
} from "@/lib/api-types";
import {
  PROPERTY_TYPE_LABELS,
  SOURCE_LABELS,
  formatBudget,
  formatDate,
  formatDateTime,
  leadName,
} from "@/lib/format";
import { availableActions } from "@/lib/lead-rules";
import { hasAny } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import {
  assignLead,
  convertLead,
  disqualifyLead,
  logActivity,
  markContacted,
  qualifyLead,
} from "./actions";
import { LeadActionBar } from "./lead-action-bar";
import { LogActivityForm } from "./log-activity";

export const metadata: Metadata = { title: "Lead" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const DONE: Record<string, string> = {
  "email-sent": "The e-mail is on its way. Its status is shown under E-mails.",
  "webcheck-queued":
    "The web check was queued. The result appears under Web check and you get a notification.",
  "email-logged": "The received e-mail was saved in the history.",
  updated: "The lead was updated.",
  assigned: "The lead was assigned.",
  contacted: "The lead was marked as contacted.",
  qualified: "The lead was qualified.",
  disqualified: "The lead was disqualified.",
  converted: "The lead was converted.",
  logged: "The activity was added to the timeline.",
  planned: "The follow-up was added to your tasks.",
  completed: "The task was marked as done.",
  cancelled: "The task was cancelled.",
  reopened: "The task is open again.",
  already_converted:
    "This lead had already been converted — nothing new was created.",
};

const ACTIVITY_LABELS: Record<Activity["kind"], string> = {
  note: "Note",
  call: "Call",
  email: "E-mail",
  meeting: "Meeting",
  created: "Created",
  status_changed: "Status",
  assigned: "Assignment",
  converted: "Conversion",
};

/** Loads a lead or turns the API's refusal into the right page (404 / no access). */
async function loadLead(id: string): Promise<Lead | "forbidden"> {
  if (!UUID.test(id)) notFound();
  try {
    return await apiFetch<Lead>(`/leads/${id}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    if (error instanceof ApiError && error.status === 403) return "forbidden";
    throw error;
  }
}

export default async function LeadPage({
  params,
  searchParams,
}: PageProps<"/leads/[id]">) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  const [lead, me] = await Promise.all([loadLead(id), getMe()]);
  if (lead === "forbidden") return <Forbidden />;

  const can = availableActions(lead, me);
  // The score card is extra information: the page works without it.
  const score = await apiFetch<LeadScore>(`/leads/${id}/score`).catch(
    () => null,
  );
  // Only website leads can have a chat (ADR 0013); like the score, the page works without it.
  const transcript =
    lead.source === "web"
      ? await apiFetch<PublicChatTranscript>(
          `/public-chat/leads/${id}/transcript`,
        ).catch(() => null)
      : null;
  const [activities, assignments, people, hasAccounts, convertedAccount] =
    await Promise.all([
      apiFetch<Activity[]>(`/leads/${id}/activities`),
      apiFetch<Assignment[]>(`/leads/${id}/assignments`),
      apiFetch<DirectoryUser[]>("/users"),
      can.convert && hasAny(me, "account:read:all", "account:read:own")
        ? apiFetch<AccountPage>("/accounts?limit=1").then(
            (page) => page.total > 0,
          )
        : Promise.resolve(false),
      lead.converted_account_id
        ? apiFetch<Account>(`/accounts/${lead.converted_account_id}`).catch(
            () => null,
          )
        : Promise.resolve(null),
    ]);

  const nameOf = (userId: string | null) =>
    userId === null
      ? "Nobody"
      : (people.find((p) => p.id === userId)?.display_name ??
        "Former colleague");
  const name = leadName(lead);
  const done = typeof query.done === "string" ? DONE[query.done] : undefined;

  const details: [string, string][] = [
    ["Company", lead.company_name ?? "—"],
    ["Job title", lead.job_title ?? "—"],
    ["E-mail", lead.email ?? "—"],
    ["Phone", lead.phone ?? "—"],
    ["Source", lead.source ? SOURCE_LABELS[lead.source] : "—"],
    ["Property type", lead.property_type ? PROPERTY_TYPE_LABELS[lead.property_type] : "—"],
    ["Budget", formatBudget(lead.budget_min_inr, lead.budget_max_inr)],
    ["Location", lead.location ?? "—"],
    ["Owner", nameOf(lead.owner_id)],
    ["Created", formatDateTime(lead.created_at)],
    ["Last updated", formatDateTime(lead.updated_at)],
  ];

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link
          href="/leads"
          className="font-medium text-brand-700 hover:underline"
        >
          ← Leads
        </Link>
      </nav>

      {done && (
        <div className="mb-4">
          <SuccessAlert>{done}</SuccessAlert>
        </div>
      )}

      <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
              {name}
            </h1>
            <StatusBadge status={lead.status} />
          </div>
          <p className="mt-1 text-sm text-slate-600">
            {lead.company_name ?? "No company"} · Owner: {nameOf(lead.owner_id)}
          </p>
        </div>
        {/* key: after any change the version changes, so dialogs re-mount closed. */}
        <LeadActionBar
          key={lead.version}
          lead={{
            id: lead.id,
            name,
            company: lead.company_name,
            ownerId: lead.owner_id,
            ownerName: nameOf(lead.owner_id),
          }}
          can={can}
          assignees={people.filter((p) => p.assignable)}
          hasAccounts={hasAccounts}
          actions={{
            assign: assignLead.bind(null, lead.id),
            markContacted: markContacted.bind(null, lead.id),
            qualify: qualifyLead.bind(null, lead.id),
            disqualify: disqualifyLead.bind(null, lead.id),
            convert: convertLead.bind(null, lead.id),
          }}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">
              Details
            </h2>
            <dl className="grid gap-x-6 gap-y-4 px-5 py-4 sm:grid-cols-2">
              {details.map(([label, value]) => (
                <div key={label}>
                  <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
                    {label}
                  </dt>
                  <dd className="mt-1 break-words text-sm text-slate-900">
                    {value}
                  </dd>
                </div>
              ))}
            </dl>
          </Card>

          {transcript && <ChatTranscriptCard transcript={transcript} />}

          <Card>
            <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">
              Timeline
            </h2>
            {/* Display only: same rule as the API (write access to this lead). */}
            {(hasAny(me, "lead:write:all") ||
              (hasAny(me, "lead:write:own") &&
                lead.owner_id === me.user_id)) && (
              <LogActivityForm action={logActivity.bind(null, lead.id)} />
            )}
            {activities.length === 0 ? (
              <p className="px-5 py-6 text-sm text-slate-600">
                No activity yet.
              </p>
            ) : (
              <ol className="divide-y divide-slate-100">
                {activities.map((a) => (
                  <li key={a.id} className="flex gap-4 px-5 py-3">
                    <span className="mt-0.5 w-24 shrink-0 text-xs font-semibold uppercase tracking-wide text-slate-500">
                      {ACTIVITY_LABELS[a.kind]}
                    </span>
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-slate-900">
                        {a.subject}
                      </p>
                      {a.body && (
                        <p className="mt-0.5 whitespace-pre-line text-sm text-slate-600">
                          {a.body}
                        </p>
                      )}
                      <p className="mt-1 text-xs text-slate-500">
                        <time dateTime={a.occurred_at}>
                          {formatDateTime(a.occurred_at)}
                        </time>{" "}
                        · {nameOf(a.actor_user_id)}
                      </p>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </Card>
          <ActivityPanel
            link={{ type: "lead", id: lead.id }}
            me={me}
            people={people}
            ownsRecord={lead.owner_id === me.user_id}
            planOnly
          />
          <RecordProposals me={me} targetId={lead.id} />
          <WebCheckCard me={me} record={{ type: "lead", id: lead.id }} />
          <EmailCard me={me} record={{ type: "lead", id: lead.id }} person={{ email: lead.email }} personLabel={name} />
        </div>

        <div className="space-y-6">
          {score && <LeadScoreCard score={score} />}
          {lead.status === "converted" && (
            <Card className="p-5">
              <h2 className="text-base font-semibold text-slate-900">
                Converted
              </h2>
              <p className="mt-1 text-sm text-slate-600">
                {lead.converted_at && `On ${formatDate(lead.converted_at)}. `}
                This lead is now read-only.
              </p>
              <dl className="mt-4 space-y-2 text-sm">
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
                    Account
                  </dt>
                  <dd className="text-slate-900">
                    {convertedAccount ? (
                      <Link
                        href={`/accounts/${convertedAccount.id}`}
                        className="text-brand-700 hover:underline"
                      >
                        {convertedAccount.name}
                      </Link>
                    ) : (
                      "Not visible to you"
                    )}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
                    Opportunity
                  </dt>
                  <dd className="text-slate-900">
                    {lead.converted_opportunity_id ? "Created" : "None"}
                  </dd>
                </div>
              </dl>
            </Card>
          )}

          <Card>
            <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">
              Ownership history
            </h2>
            {assignments.length === 0 ? (
              <p className="px-5 py-6 text-sm text-slate-600">
                Never assigned.
              </p>
            ) : (
              <ol className="divide-y divide-slate-100">
                {assignments.map((h) => (
                  <li key={h.id} className="px-5 py-3 text-sm">
                    <p className="text-slate-900">
                      {h.from_user_id ? `${nameOf(h.from_user_id)} → ` : ""}
                      <strong>{nameOf(h.to_user_id)}</strong>
                    </p>
                    {h.reason && <p className="text-slate-600">{h.reason}</p>}
                    <p className="mt-1 text-xs text-slate-500">
                      <time dateTime={h.assigned_at}>
                        {formatDateTime(h.assigned_at)}
                      </time>{" "}
                      · by {nameOf(h.assigned_by_user_id)}
                    </p>
                  </li>
                ))}
              </ol>
            )}
          </Card>
        </div>
      </div>
    </>
  );
}
