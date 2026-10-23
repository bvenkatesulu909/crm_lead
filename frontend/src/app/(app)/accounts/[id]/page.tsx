import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { ActivityPanel } from "@/components/activity-panel";
import { DocumentsCard } from "@/components/documents-card";
import { PaymentStateBadge, invoiceNumber } from "@/components/invoices";
import {
  OrderStatusBadge,
  formatMoney,
  orderNumber,
} from "@/components/orders";
import { ContractStatusBadge, EndHint } from "@/components/contract-view";
import { QuoteStatusBadge } from "@/components/quote-view";
import { TicketStatusBadge, ticketNumber } from "@/components/tickets";
import {
  AccountStatus,
  ButtonLink,
  Card,
  Forbidden,
  StatusBadge,
  SuccessAlert,
} from "@/components/ui";
import { ApiError } from "@/lib/api-error";
import type {
  Account,
  AccountPage,
  ContactPage,
  CustomerHealth,
  DirectoryUser,
  InvoicePage,
  LeadPage,
  OpportunityPage,
  OrderPage,
  PortalUser,
  ContractPage,
  QuotePage,
  TicketPage,
  TimelineEntry,
} from "@/lib/api-types";
import { formatAmounts } from "@/lib/dashboard";
import {
  ACCOUNT_TYPE_LABELS,
  HEALTH_LABELS,
  LIFECYCLE_LABELS,
  countryName,
  languageName,
  CHANNEL_LABELS,
  CONSENT_LABELS,
  SEGMENT_LABELS,
  STAGE_LABELS,
  contactName,
  relationshipTimeline,
} from "@/lib/customer-data";
import { formatDate, formatDateTime, leadName } from "@/lib/format";
import {
  canInvitePortalUsers,
  canManageAccounts,
  canManageUsers,
  canReadContacts,
  canReadInvoices,
  canReadLeads,
  canReadOpportunities,
  canReadOrders,
  canReadContracts,
  canReadQuotes,
  canReadTickets,
  canWriteAccounts,
  canWriteContacts,
  canWriteOpportunities,
  canWriteOrders,
  canWriteContracts,
  canWriteQuotes,
} from "@/lib/permissions";
import { quoteNumber } from "@/lib/quotes";
import { apiFetch, getMe } from "@/lib/server/api";

import {
  archiveAccount,
  changeAccountStatus,
  transferAccount,
} from "../actions";
import { AccountActions } from "./account-actions";
import { PortalAccessCard } from "./portal-access";
import { invitePortalUser, revokePortalAccess } from "./portal-actions";

export const metadata: Metadata = { title: "Account" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Loads an account or turns the API's refusal into the right page (404 / no access). */
async function loadAccount(id: string): Promise<Account | "forbidden"> {
  if (!UUID.test(id)) notFound();
  try {
    return await apiFetch<Account>(`/accounts/${id}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    if (error instanceof ApiError && error.status === 403) return "forbidden";
    throw error;
  }
}

/** Loads a section only if the role includes it; a failing section never breaks the page. */
function section<T>(
  allowed: boolean,
  load: () => Promise<T>,
): Promise<T | null> {
  return allowed ? load().catch(() => null) : Promise.resolve(null);
}

const DONE: Record<string, string> = {
  invited: "The invitation was sent. The customer sets a password and then sees this account.",
  revoked: "Portal access was removed for this account.",
  created: "The account was created.",
  planned: "The task was added.",
  logged: "The activity was logged.",
  completed: "The task was marked as done.",
  cancelled: "The task was cancelled.",
  reopened: "The task is open again.",
  updated: "Your changes were saved.",
  deactivated: "The account is now inactive.",
  activated: "The account is active again.",
  restored: "The account was restored from the archive.",
  transferred: "The customer was transferred to the new owner.",
  "document-uploaded": "The document was uploaded.",
  "document-deleted": "The document was deleted.",
}; // prettier-ignore

function SectionCard({
  title,
  action,
  children,
}: {
  title: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Card>
      <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-5 py-4">
        <h2 className="text-base font-semibold text-slate-900">{title}</h2>
        {action}
      </div>
      {children}
    </Card>
  );
}

const HEALTH_STYLE = {
  healthy: "bg-emerald-50 text-emerald-800",
  watch: "bg-amber-50 text-amber-800",
  at_risk: "bg-red-50 text-red-800",
} as const;

/** Customer health: score, the factors behind it, inactivity and lifetime value. */
function HealthCard({ health }: { health: CustomerHealth }) {
  return (
    <Card>
      <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-5 py-4">
        <h2 className="text-base font-semibold text-slate-900">Customer health</h2>
        <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${HEALTH_STYLE[health.label]}`}>
          {HEALTH_LABELS[health.label]} · {health.score}/100
        </span>
      </div>
      <div className="space-y-3 px-5 py-4 text-sm">
        <p className="text-slate-700">
          {health.last_interaction_at
            ? `Last interaction ${formatDate(health.last_interaction_at)} (${health.days_inactive} days ago)`
            : "No interaction recorded yet"}
          {health.inactive && <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-900">Inactive</span>}
        </p>
        {health.factors.length > 0 && (
          <ul className="space-y-1">
            {health.factors.map((f) => (
              <li key={f.label} className="flex justify-between gap-3 text-xs">
                <span className="text-slate-600">{f.label}</span>
                <span className={f.impact < 0 ? "font-medium text-red-700" : "font-medium text-emerald-700"}>
                  {f.impact > 0 ? `+${f.impact}` : f.impact}
                </span>
              </li>
            ))}
          </ul>
        )}
        <p className="border-t border-slate-100 pt-3 text-xs text-slate-600">
          Lifetime value (issued invoices): <strong>{formatAmounts(health.lifetime_value)}</strong>
        </p>
      </div>
    </Card>
  ); // prettier-ignore
}

const Empty = ({ children }: { children: ReactNode }) => (
  <p className="px-5 py-6 text-sm text-slate-600">{children}</p>
);

export default async function AccountPage({
  params,
  searchParams,
}: PageProps<"/accounts/[id]">) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  const done = typeof query.done === "string" ? DONE[query.done] : undefined;
  const [account, me] = await Promise.all([loadAccount(id), getMe()]);
  if (account === "forbidden") return <Forbidden />;
  const a = account.id;

  // Every list comes from the API, which returns only records this user may see.
  const [
    people, parent, children, contacts, opportunities, history, orders, invoices, tickets,
    portalUsers, audit, health, quotes, contracts,
  ] = await Promise.all([
    apiFetch<DirectoryUser[]>("/users"),
    account.parent_account_id
      ? apiFetch<Account>(`/accounts/${account.parent_account_id}`).catch(() => null)
      : Promise.resolve(null),
    apiFetch<AccountPage>(`/accounts?parent_account_id=${a}&limit=50`).catch(() => null),
    section(canReadContacts(me), () => apiFetch<ContactPage>(`/contacts?account_id=${a}&limit=100`)),
    section(canReadOpportunities(me), () => apiFetch<OpportunityPage>(`/opportunities?account_id=${a}&limit=20`)),
    section(canReadLeads(me), () => apiFetch<LeadPage>(`/leads?account_id=${a}&limit=50&sort=-created_at`)),
    section(canReadOrders(me), () => apiFetch<OrderPage>(`/orders?account_id=${a}&limit=10`)),
    section(canReadInvoices(me), () => apiFetch<InvoicePage>(`/invoices?account_id=${a}&limit=10`)),
    section(canReadTickets(me), () => apiFetch<TicketPage>(`/tickets?account_id=${a}&limit=10`)),
    apiFetch<PortalUser[]>(`/accounts/${a}/portal-users`).catch(() => null),
    apiFetch<TimelineEntry[]>(`/accounts/${a}/timeline`).catch(() => null),
    apiFetch<CustomerHealth>(`/accounts/${a}/health`).catch(() => null),
    section(canReadQuotes(me), () => apiFetch<QuotePage>(`/quotes?account_id=${a}&limit=10`)),
    section(canReadContracts(me), () => apiFetch<ContractPage>(`/contracts?account_id=${a}&limit=10`)),
  ]); // prettier-ignore

  // Display only: the API applies the same rules again on every change.
  const isOwner = account.owner_id === me.user_id;
  const mayEdit = canWriteAccounts(me) && (canManageAccounts(me) || isOwner);
  const mayInvite = canInvitePortalUsers(me) && (canManageUsers(me) || isOwner);
  const mayAddContact = canWriteContacts(me) && mayEdit;
  const personName = (userId: string | null) =>
    userId === null
      ? "Nobody"
      : (people.find((p) => p.id === userId)?.display_name ??
        "Former colleague");

  const timeline = relationshipTimeline({
    audit: audit ?? [],
    orders: orders?.items,
    invoices: invoices?.items,
    tickets: tickets?.items,
    leads: history?.items,
  });

  const details: [string, ReactNode][] = [
    ["Account number", account.account_number ?? "—"],
    ["Segment", account.segment ? SEGMENT_LABELS[account.segment] : "—"],
    ["Industry", account.industry ?? "—"],
    ["Preferred channel", account.preferred_channel ? CHANNEL_LABELS[account.preferred_channel] : "—"],
    ["Preferred language", languageName(account.preferred_language)],
    ["Lifecycle stage", account.lifecycle_stage ? LIFECYCLE_LABELS[account.lifecycle_stage] : "—"],
    ["Account type", ACCOUNT_TYPE_LABELS[account.account_type]],
    ["Location", [account.city, account.region, account.country ? countryName(account.country) : null].filter(Boolean).join(", ") || "—"],
    ["Phone", account.phone ?? "—"],
    [
      "Website",
      account.website && /^https?:\/\//.test(account.website) ? (
        <a href={account.website} rel="noopener noreferrer nofollow" target="_blank" className="text-brand-700 hover:underline">
          {account.website}
        </a>
      ) : (account.website ?? "—"),
    ],
    ["Owner", personName(account.owner_id)],
    ["Team", <span key="team" className="text-slate-500">Teams come with a later phase</span>],
    ["Created", formatDateTime(account.created_at)],
    ["Last updated", formatDateTime(account.updated_at)],
  ]; // prettier-ignore

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link href="/accounts" className="font-medium text-brand-700 hover:underline">
          ← Accounts
        </Link>
      </nav>
      {done && (
        <div className="mb-4">
          <SuccessAlert>{done}</SuccessAlert>
        </div>
      )}
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{account.name}</h1>
            <AccountStatus status={account.status} />
            {account.segment && (
              <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-700">
                {SEGMENT_LABELS[account.segment]}
              </span>
            )}
          </div>
          <p className="mt-1 text-sm text-slate-600">Owner: {personName(account.owner_id)}</p>
        </div>
        <AccountActions
          accountId={a}
          status={account.status}
          canEdit={mayEdit}
          canArchive={canManageAccounts(me)}
          changeStatus={changeAccountStatus.bind(null, a, account.version, account.status === "active" ? "inactive" : "active")}
          archive={archiveAccount.bind(null, a, account.version)}
          transfer={
            canManageAccounts(me)
              ? {
                  action: transferAccount.bind(null, a, account.version),
                  owners: people
                    .filter((p) => p.assignable && p.id !== account.owner_id)
                    .map((p) => ({ id: p.id, name: p.display_name })),
                }
              : undefined
          }
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">Profile</h2>
            <dl className="grid gap-x-6 gap-y-4 px-5 py-4 sm:grid-cols-2">
              {details.map(([label, value]) => (
                <div key={label}>
                  <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</dt>
                  <dd className="mt-1 break-words text-sm text-slate-900">{value}</dd>
                </div>
              ))}
            </dl>
          </Card>

          {contacts && (
            <SectionCard
              title={`Contacts (${contacts.total})`}
              action={mayAddContact && (
                <ButtonLink href={`/contacts/new?account=${a}`} variant="secondary">Add contact</ButtonLink>
              )}
            >
              {contacts.items.length === 0 ? (
                <Empty>No contacts for this account yet.</Empty>
              ) : (
                <ul className="divide-y divide-slate-100">
                  {contacts.items.map((c) => (
                    <li key={c.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
                      <div className="min-w-0">
                        <p className="text-sm font-medium">
                          <Link href={`/contacts/${c.id}`} className="text-brand-700 hover:underline">{contactName(c)}</Link>
                          {c.is_primary && (
                            <span className="ml-2 rounded-full bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-700">Primary</span>
                          )}
                        </p>
                        <p className="truncate text-xs text-slate-500">
                          {[c.job_title, c.department].filter(Boolean).join(" · ") || "No designation"}
                          {c.email && ` · ${c.email}`}
                          {(c.phone || c.mobile) && ` · ${c.phone ?? c.mobile}`}
                        </p>
                      </div>
                      <div className="flex flex-wrap gap-2 text-xs">
                        {c.preferred_channel && (
                          <span className="rounded bg-slate-100 px-2 py-0.5 text-slate-700">Prefers {CHANNEL_LABELS[c.preferred_channel].toLowerCase()}</span>
                        )}
                        <span className="rounded bg-slate-100 px-2 py-0.5 text-slate-700">{CONSENT_LABELS[c.email_consent]}</span>
                        {c.do_not_call && <span className="rounded bg-amber-50 px-2 py-0.5 text-amber-800">Do not call</span>}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </SectionCard>
          )}

          {opportunities && (
            <SectionCard
              title="Opportunities"
              action={canWriteOpportunities(me) && mayEdit && (
                <ButtonLink href={`/opportunities/new?account=${a}`} variant="secondary">New opportunity</ButtonLink>
              )}
            >
              {opportunities.items.length === 0 ? (
                <Empty>No opportunities for this account.</Empty>
              ) : (
                <ul className="divide-y divide-slate-100">
                  {opportunities.items.map((o) => (
                    <li key={o.id} className="flex items-center justify-between gap-3 px-5 py-3">
                      <div className="min-w-0">
                        <Link href={`/opportunities/${o.id}`} className="block truncate text-sm font-medium text-brand-700 hover:underline">{o.name}</Link>
                        <p className="text-xs text-slate-500">
                          {o.amount ? formatMoney(o.amount, o.currency) : "No amount yet"}
                          {o.expected_close_date && ` · closes ${formatDate(o.expected_close_date)}`}
                          {` · ${personName(o.owner_id)}`}
                        </p>
                      </div>
                      <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-700">
                        {STAGE_LABELS[o.stage] ?? o.stage}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </SectionCard>
          )}

          <ActivityPanel link={{ type: "account", id: a }} me={me} people={people} ownsRecord={isOwner} />

          <SectionCard title="Relationship timeline">
            {timeline.length === 0 ? (
              <Empty>Nothing has happened yet.</Empty>
            ) : (
              <ol className="divide-y divide-slate-100">
                {timeline.map((t, index) => (
                  <li key={`${t.at}-${index}`} className="px-5 py-3">
                    <p className="text-sm font-medium text-slate-900">
                      {t.href ? <Link href={t.href} className="hover:text-brand-700 hover:underline">{t.title}</Link> : t.title}
                    </p>
                    <p className="text-xs text-slate-500">
                      {formatDateTime(t.at)}
                      {t.by && ` · ${t.by}`}
                    </p>
                    {t.details.length > 0 && (
                      <ul className="mt-1 space-y-0.5 text-xs text-slate-600">
                        {t.details.map((d) => <li key={d}>{d}</li>)}
                      </ul>
                    )}
                  </li>
                ))}
              </ol>
            )}
          </SectionCard>
        </div>

        <div className="space-y-6">
          {health && <HealthCard health={health} />}
          <SectionCard
            title="Company hierarchy"
            action={mayEdit && (
              <ButtonLink href={`/accounts/new?parent=${a}`} variant="secondary">Add child</ButtonLink>
            )}
          >
            <div className="space-y-3 px-5 py-4 text-sm">
              <p>
                <span className="text-slate-500">Parent: </span>
                {parent ? (
                  <Link href={`/accounts/${parent.id}`} className="text-brand-700 hover:underline">{parent.name}</Link>
                ) : account.parent_account_id ? "Not visible to you" : "None"}
              </p>
              <div>
                <p className="text-slate-500">Child accounts:</p>
                {children && children.items.length > 0 ? (
                  <ul className="mt-1 list-inside list-disc">
                    {children.items.map((c) => (
                      <li key={c.id}>
                        <Link href={`/accounts/${c.id}`} className="text-brand-700 hover:underline">{c.name}</Link>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-1 text-slate-600">None</p>
                )}
              </div>
            </div>
          </SectionCard>

          <DocumentsCard me={me} recordType="account" recordId={a} />

          {quotes && (
            <SectionCard
              title="Quotes"
              action={canWriteQuotes(me) && (
                <ButtonLink href={`/quotes/new?account=${a}`} variant="secondary">New quote</ButtonLink>
              )}
            >
              {quotes.items.length === 0 ? (
                <Empty>No quotes for this account.</Empty>
              ) : (
                <ul className="divide-y divide-slate-100">
                  {quotes.items.map((q) => (
                    <li key={q.id} className="flex items-center justify-between gap-3 px-5 py-3">
                      <div className="min-w-0">
                        <Link href={`/quotes/${q.id}`} className="text-sm font-medium text-brand-700 hover:underline">
                          <span className="font-mono">{quoteNumber(q.number, q.revision)}</span> {q.title}
                        </Link>
                        <p className="text-xs text-slate-500">{formatMoney(q.total, q.currency)} · valid until {formatDate(q.valid_until)}</p>
                      </div>
                      <QuoteStatusBadge status={q.status} expired={q.expired} />
                    </li>
                  ))}
                </ul>
              )}
              {quotes.total > quotes.items.length && (
                <p className="border-t border-slate-100 px-5 py-3 text-sm">
                  <Link href={`/quotes?account_id=${a}`} className="text-brand-700 hover:underline">All {quotes.total} quotes</Link>
                </p>
              )}
            </SectionCard>
          )}

          {contracts && (
            <SectionCard
              title="Contracts"
              action={canWriteContracts(me) && (
                <ButtonLink href={`/contracts/new?account=${a}`} variant="secondary">New contract</ButtonLink>
              )}
            >
              {contracts.items.length === 0 ? (
                <Empty>No contracts for this account.</Empty>
              ) : (
                <ul className="divide-y divide-slate-100">
                  {contracts.items.map((c) => (
                    <li key={c.id} className="flex items-center justify-between gap-3 px-5 py-3">
                      <div className="min-w-0">
                        <Link href={`/contracts/${c.id}`} className="text-sm font-medium text-brand-700 hover:underline">
                          <span className="font-mono">{c.label}</span> {c.title}
                        </Link>
                        <p className="text-xs text-slate-500">
                          {formatMoney(c.total_value, c.currency)}{c.end_date && ` · ends ${formatDate(c.end_date)}`} <EndHint status={c.status} daysToEnd={c.days_to_end} />
                        </p>
                      </div>
                      <ContractStatusBadge status={c.status} />
                    </li>
                  ))}
                </ul>
              )}
              {contracts.total > contracts.items.length && (
                <p className="border-t border-slate-100 px-5 py-3 text-sm">
                  <Link href={`/contracts?account_id=${a}`} className="text-brand-700 hover:underline">All {contracts.total} contracts</Link>
                </p>
              )}
            </SectionCard>
          )}

          {orders && (
            <SectionCard
              title="Orders"
              action={canWriteOrders(me) && (
                <ButtonLink href={`/orders/new?account=${a}`} variant="secondary">New order</ButtonLink>
              )}
            >
              {orders.items.length === 0 ? (
                <Empty>No orders for this account.</Empty>
              ) : (
                <ul className="divide-y divide-slate-100">
                  {orders.items.map((o) => (
                    <li key={o.id} className="flex items-center justify-between gap-3 px-5 py-3">
                      <div className="min-w-0">
                        <Link href={`/orders/${o.id}`} className="font-mono text-sm font-medium text-brand-700 hover:underline">{orderNumber(o.number)}</Link>
                        <p className="text-xs text-slate-500">{formatMoney(o.total, o.currency)} · {formatDate(o.created_at)}</p>
                      </div>
                      <OrderStatusBadge status={o.status} />
                    </li>
                  ))}
                </ul>
              )}
            </SectionCard>
          )}

          {invoices && (
            <SectionCard title="Invoices">
              {invoices.items.length === 0 ? (
                <Empty>No invoices for this account.</Empty>
              ) : (
                <ul className="divide-y divide-slate-100">
                  {invoices.items.map((i) => (
                    <li key={i.id} className="flex items-center justify-between gap-3 px-5 py-3">
                      <div className="min-w-0">
                        <Link href={`/invoices/${i.id}`} className="font-mono text-sm font-medium text-brand-700 hover:underline">{invoiceNumber(i.number)}</Link>
                        <p className="text-xs text-slate-500">
                          {formatMoney(i.total, i.currency)}
                          {i.balance_due !== "0.00" && i.number !== null && ` · ${formatMoney(i.balance_due, i.currency)} due`}
                          {i.due_date && ` · due ${formatDate(i.due_date)}`}
                        </p>
                      </div>
                      <PaymentStateBadge state={i.payment_state} />
                    </li>
                  ))}
                </ul>
              )}
            </SectionCard>
          )}

          {tickets && (
            <SectionCard title="Support tickets">
              {tickets.items.length === 0 ? (
                <Empty>No support tickets for this account.</Empty>
              ) : (
                <ul className="divide-y divide-slate-100">
                  {tickets.items.map((t) => (
                    <li key={t.id} className="flex items-center justify-between gap-3 px-5 py-3">
                      <div className="min-w-0">
                        <Link href={`/tickets/${t.id}`} className="text-sm font-medium text-brand-700 hover:underline">
                          {ticketNumber(t.number)} · {t.subject}
                        </Link>
                        <p className="text-xs text-slate-500">Opened {formatDate(t.created_at)}</p>
                      </div>
                      <TicketStatusBadge status={t.status} />
                    </li>
                  ))}
                </ul>
              )}
            </SectionCard>
          )}

          <SectionCard title="Converted leads">
            {history === null ? (
              <Empty>Lead history isn&apos;t part of your role.</Empty>
            ) : history.items.length === 0 ? (
              <Empty>No leads were converted into this account.</Empty>
            ) : (
              <ul className="divide-y divide-slate-100">
                {history.items.map((lead) => (
                  <li key={lead.id} className="flex items-center justify-between gap-3 px-5 py-3">
                    <div className="min-w-0">
                      <Link href={`/leads/${lead.id}`} className="block truncate text-sm font-medium text-brand-700 hover:underline">{leadName(lead)}</Link>
                      <p className="text-xs text-slate-500">Converted {lead.converted_at ? formatDate(lead.converted_at) : ""}</p>
                    </div>
                    <StatusBadge status={lead.status} />
                  </li>
                ))}
              </ul>
            )}
          </SectionCard>

          {portalUsers && (
            <PortalAccessCard
              accountName={account.name}
              users={portalUsers}
              invite={mayInvite ? invitePortalUser.bind(null, a) : undefined}
              revoke={
                mayInvite
                  ? Object.fromEntries(portalUsers.map((u) => [u.id, revokePortalAccess.bind(null, a, u.id)]))
                  : undefined
              }
            />
          )}
        </div>
      </div>
    </>
  ); // prettier-ignore
}
