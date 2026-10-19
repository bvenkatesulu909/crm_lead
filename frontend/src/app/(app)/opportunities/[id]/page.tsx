import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { ActivityPanel } from "@/components/activity-panel";
import { DocumentsCard } from "@/components/documents-card";
import { QuoteStatusBadge } from "@/components/quote-view";
import { ButtonLink, Card, Forbidden, SuccessAlert, cx } from "@/components/ui";
import { ApiError } from "@/lib/api-error";
import {
  OPEN_STAGES,
  type Account,
  type Contact,
  type DirectoryUser,
  type Opportunity,
  type QuotePage,
  type StageChange,
} from "@/lib/api-types";
import { contactName } from "@/lib/customer-data";
import { formatAmounts } from "@/lib/dashboard";
import { formatDate, formatDateTime } from "@/lib/format";
import {
  canManageOpportunities,
  canReadQuotes,
  canWriteQuotes,
  hasAny,
} from "@/lib/permissions";
import { STAGE_LABELS } from "@/lib/pipeline";
import { quoteNumber } from "@/lib/quotes";
import { apiFetch, getMe } from "@/lib/server/api";

import { markLost, markWon, moveStage, reopenOpportunity } from "../actions";
import { OpportunityActions } from "./opportunity-actions";

export const metadata: Metadata = { title: "Opportunity" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const DONE: Record<string, string> = {
  "document-uploaded": "The document was uploaded.",
  "document-deleted": "The document was deleted.",
  created: "The opportunity was created.",
  updated: "Your changes were saved.",
  moved: "The deal moved to its new stage.",
  won: "The deal was marked as won.",
  lost: "The deal was marked as lost.",
  reopened: "The deal is open again.",
  planned: "The task was added.",
  logged: "The activity was logged.",
  completed: "The task was marked as done.",
  cancelled: "The task was cancelled.",
};

async function load(id: string): Promise<Opportunity | "forbidden"> {
  if (!UUID.test(id)) notFound();
  try {
    return await apiFetch<Opportunity>(`/opportunities/${id}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    if (error instanceof ApiError && error.status === 403) return "forbidden";
    throw error;
  }
}

function Stepper({ opp }: { opp: Opportunity }) {
  const lost = opp.stage === "closed_lost";
  const index =
    opp.stage === "closed_won"
      ? OPEN_STAGES.length
      : OPEN_STAGES.indexOf(opp.stage as never);
  const steps = [...OPEN_STAGES, lost ? "closed_lost" : "closed_won"] as const;
  return (
    <ol aria-label="Pipeline stage" className="flex flex-wrap gap-1">
      {steps.map((s, i) => {
        const current = s === opp.stage;
        const passed = !lost && i < index;
        return (
          <li key={s} aria-current={current ? "step" : undefined}
            className={cx("rounded-full px-3 py-1 text-xs font-medium",
              current && (lost ? "bg-red-600 text-white" : "bg-brand-600 text-white"),
              !current && passed && "bg-brand-50 text-brand-700",
              !current && !passed && "bg-slate-100 text-slate-500")}>
            {STAGE_LABELS[s]}
          </li>
        );
      })}
    </ol>
  ); // prettier-ignore
}

export default async function OpportunityPage({
  params,
  searchParams,
}: PageProps<"/opportunities/[id]">) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  const done = typeof query.done === "string" ? DONE[query.done] : undefined;
  const [opp, me] = await Promise.all([load(id), getMe()]);
  if (opp === "forbidden") return <Forbidden />;

  const [account, contact, people, history, quotes] = await Promise.all([
    apiFetch<Account>(`/accounts/${opp.account_id}`).catch(() => null),
    opp.primary_contact_id ? apiFetch<Contact>(`/contacts/${opp.primary_contact_id}`).catch(() => null) : Promise.resolve(null),
    apiFetch<DirectoryUser[]>("/users").catch(() => []),
    apiFetch<StageChange[]>(`/opportunities/${opp.id}/stages`).catch(() => []),
    canReadQuotes(me) ? apiFetch<QuotePage>(`/quotes?opportunity_id=${opp.id}&limit=10`).catch(() => null) : Promise.resolve(null),
  ]); // prettier-ignore
  const person = (uid: string | null) =>
    uid
      ? (people.find((p) => p.id === uid)?.display_name ?? "Former colleague")
      : "Nobody";
  const isOwner = opp.owner_id === me.user_id;
  const canEdit =
    canManageOpportunities(me) ||
    (hasAny(me, "opportunity:write:own") && isOwner);
  const value = (amount: string | null) =>
    amount === null ? "—" : formatAmounts([{ currency: opp.currency, amount }]);

  const details: [string, ReactNode][] = [
    ["Account", account ? <Link href={`/accounts/${account.id}`} className="text-brand-700 hover:underline">{account.name}</Link> : "Not visible to you"],
    ["Primary contact", contact ? <Link href={`/contacts/${contact.id}`} className="text-brand-700 hover:underline">{contactName(contact)}</Link> : opp.primary_contact_id ? "Not visible to you" : "—"],
    ["Estimated value", value(opp.amount)],
    ["Probability", `${opp.probability}%`],
    ["Weighted value", value(opp.weighted_amount)],
    ["Expected close", opp.expected_close_date ? formatDate(opp.expected_close_date) : "—"],
    ["Deal owner", person(opp.owner_id)],
    ["Next step", opp.next_step ?? "—"],
    ...(opp.closed_at ? ([["Closed", formatDateTime(opp.closed_at)]] as [string, ReactNode][]) : []),
    ...(opp.lost_reason ? ([["Lost because", opp.lost_reason]] as [string, ReactNode][]) : []),
  ]; // prettier-ignore

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link href="/opportunities" className="font-medium text-brand-700 hover:underline">← Pipeline</Link>
      </nav>
      {done && <div className="mb-4"><SuccessAlert>{done}</SuccessAlert></div>}
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{opp.name}</h1>
          <Stepper opp={opp} />
        </div>
        <OpportunityActions
          key={opp.version}
          id={opp.id}
          stage={opp.stage}
          hasAmount={opp.amount !== null}
          canEdit={canEdit}
          canReopen={canManageOpportunities(me)}
          actions={{
            move: moveStage.bind(null, opp.id, opp.version),
            won: markWon.bind(null, opp.id, opp.version),
            lost: markLost.bind(null, opp.id, opp.version),
            reopen: reopenOpportunity.bind(null, opp.id, opp.version),
          }}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">Deal</h2>
            <dl className="grid gap-x-6 gap-y-4 px-5 py-4 sm:grid-cols-2">
              {details.map(([label, v]) => (
                <div key={label}>
                  <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</dt>
                  <dd className="mt-1 break-words text-sm text-slate-900">{v}</dd>
                </div>
              ))}
            </dl>
            {opp.description && <p className="whitespace-pre-line border-t border-slate-100 px-5 py-4 text-sm text-slate-700">{opp.description}</p>}
          </Card>
          <DocumentsCard me={me} recordType="opportunity" recordId={opp.id} />
          {quotes && (
            <Card>
              <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-5 py-4">
                <h2 className="text-base font-semibold text-slate-900">Quotes</h2>
                {canWriteQuotes(me) &&
                  (OPEN_STAGES as readonly string[]).includes(opp.stage) && (
                  <ButtonLink href={`/quotes/new?account=${opp.account_id}&opportunity=${opp.id}`} variant="secondary">New quote</ButtonLink>
                )}
              </div>
              {quotes.items.length === 0 ? (
                <p className="px-5 py-6 text-sm text-slate-600">No quotes for this deal yet.</p>
              ) : (
                <ul className="divide-y divide-slate-100">
                  {quotes.items.map((q) => (
                    <li key={q.id} className="flex items-center justify-between gap-3 px-5 py-3">
                      <div className="min-w-0">
                        <Link href={`/quotes/${q.id}`} className="text-sm font-medium text-brand-700 hover:underline">
                          <span className="font-mono">{quoteNumber(q.number, q.revision)}</span> {q.title}
                        </Link>
                        <p className="text-xs text-slate-500">{formatAmounts([{ currency: q.currency, amount: q.total }])} · valid until {formatDate(q.valid_until)}</p>
                      </div>
                      <QuoteStatusBadge status={q.status} expired={q.expired} />
                    </li>
                  ))}
                </ul>
              )}
              {quotes.total > quotes.items.length && (
                <p className="border-t border-slate-100 px-5 py-3 text-sm">
                  <Link href={`/quotes?opportunity_id=${opp.id}`} className="text-brand-700 hover:underline">All {quotes.total} quotes</Link>
                </p>
              )}
            </Card>
          )}
          <ActivityPanel link={{ type: "opportunity", id: opp.id }} me={me} people={people} ownsRecord={isOwner} />
        </div>
        <Card>
          <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">Stage history</h2>
          <ol className="divide-y divide-slate-100">
            {history.map((h, i) => (
              <li key={`${h.changed_at}-${i}`} className="px-5 py-3">
                <p className="text-sm font-medium text-slate-900">
                  {h.from_stage ? `${STAGE_LABELS[h.from_stage]} → ${STAGE_LABELS[h.to_stage]}` : `Created in ${STAGE_LABELS[h.to_stage]}`}
                </p>
                <p className="text-xs text-slate-500">{formatDateTime(h.changed_at)}{h.changed_by_name && ` · ${h.changed_by_name}`}</p>
                {h.note && h.note !== "Created" && <p className="mt-0.5 text-xs text-slate-600">{h.note}</p>}
              </li>
            ))}
          </ol>
        </Card>
      </div>
    </>
  ); // prettier-ignore
}
