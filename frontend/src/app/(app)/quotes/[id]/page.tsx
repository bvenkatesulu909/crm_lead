import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import {
  FileProblem,
  QuoteLinesTable,
  QuoteStatusBadge,
  QuoteTotals,
} from "@/components/quote-view";
import { Card, Forbidden, SuccessAlert } from "@/components/ui";
import { ApiError } from "@/lib/api-error";
import type {
  Account,
  Contact,
  DirectoryUser,
  Opportunity,
  Quote,
  QuoteEvent,
} from "@/lib/api-types";
import { contactName } from "@/lib/customer-data";
import { formatDate, formatDateTime } from "@/lib/format";
import {
  canApproveQuotes,
  canWriteOrders,
  canWriteQuotes,
  hasAny,
} from "@/lib/permissions";
import { QUOTE_STATUS_LABELS, quoteNumber } from "@/lib/quotes";
import { apiFetch, getMe } from "@/lib/server/api";

import { emailQuote, quoteStep } from "../actions";
import { QuoteActions } from "./quote-actions";

export const metadata: Metadata = { title: "Quote" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const EMAIL_STATUS: Record<NonNullable<Quote["email_status"]>, string> = {
  sending: "On its way…",
  sent: "Sent to the contact",
  failed: "Could not be sent - see the history",
};

const DONE: Record<string, string> = {
  created: "The quote was created.",
  updated: "Your changes were saved.",
  submitted: "The quote was submitted.",
  emailed:
    "The e-mail is on its way, with the PDF attached. The customer can also see the quote in the portal.",
  approved: "The quote was approved.",
  rejected: "The quote went back to draft.",
  sent: "The quote is marked as sent. The customer can now see it in the portal.",
  accepted: "The acceptance was recorded.",
  declined: "The decline was recorded.",
  revised: "A new revision was created.",
  ordered: "A draft order was created from this quote.",
};

export default async function QuotePage({
  params,
  searchParams,
}: PageProps<"/quotes/[id]">) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  if (!UUID.test(id)) notFound();
  const me = await getMe();
  let quote: Quote;
  try {
    quote = await apiFetch<Quote>(`/quotes/${id}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    if (error instanceof ApiError && error.status === 403) return <Forbidden />;
    throw error;
  }
  const [account, deal, contact, people, history] = await Promise.all([
    apiFetch<Account>(`/accounts/${quote.account_id}`).catch(() => null),
    quote.opportunity_id ? apiFetch<Opportunity>(`/opportunities/${quote.opportunity_id}`).catch(() => null) : Promise.resolve(null),
    quote.contact_id ? apiFetch<Contact>(`/contacts/${quote.contact_id}`).catch(() => null) : Promise.resolve(null),
    apiFetch<DirectoryUser[]>("/users").catch(() => []),
    apiFetch<QuoteEvent[]>(`/quotes/${id}/history`).catch(() => []),
  ]); // prettier-ignore
  const person = (uid: string | null) =>
    uid
      ? (people.find((p) => p.id === uid)?.display_name ?? "Former colleague")
      : "—";
  const done = typeof query.done === "string" ? DONE[query.done] : undefined;
  const mine =
    quote.owner_id === me.user_id || account?.owner_id === me.user_id;
  const canWrite =
    canWriteQuotes(me) && (hasAny(me, "quote:write:all") || mine);
  const step = (s: Parameters<typeof quoteStep>[2]) =>
    quoteStep.bind(null, quote.id, quote.version, s);

  const details: [string, ReactNode][] = [
    ["Account", account ? <Link href={`/accounts/${account.id}`} className="text-brand-700 hover:underline">{account.name}</Link> : "—"],
    ["Deal", deal ? <Link href={`/opportunities/${deal.id}`} className="text-brand-700 hover:underline">{deal.name}</Link> : quote.opportunity_id ? "Not visible to you" : "—"],
    ["For", contact ? contactName(contact) : "—"],
    ["Owner", person(quote.owner_id)],
    ["Valid until", formatDate(quote.valid_until)],
    ["Approval", quote.needs_approval ? (quote.approved_by_user_id ? `Approved by ${person(quote.approved_by_user_id)}` : "Needs a manager (discount above limit)") : "Not needed"],
    ...(quote.order_id ? ([["Order", <Link key="o" href={`/orders/${quote.order_id}`} className="text-brand-700 hover:underline">Open the order</Link>]] as [string, ReactNode][]) : []),
    ...(quote.revision_of_id ? ([["Previous revision", <Link key="r" href={`/quotes/${quote.revision_of_id}`} className="text-brand-700 hover:underline">View</Link>]] as [string, ReactNode][]) : []),
    ...(quote.email_status ? ([["E-mail", EMAIL_STATUS[quote.email_status]]] as [string, ReactNode][]) : []),
    ...(quote.decision_note ? ([["Customer's answer", quote.decision_note]] as [string, ReactNode][]) : []),
  ]; // prettier-ignore

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link href="/quotes" className="font-medium text-brand-700 hover:underline">← Quotes</Link>
      </nav>
      {done && <div className="mb-4"><SuccessAlert>{done}</SuccessAlert></div>}
      <FileProblem reason={query.file} />
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="font-mono text-sm text-slate-500">{quoteNumber(quote.number, quote.revision)}</p>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{quote.title}</h1>
          <div className="mt-2"><QuoteStatusBadge status={quote.status} expired={quote.expired} /></div>
        </div>
        <QuoteActions
          key={quote.version}
          id={quote.id}
          status={quote.status}
          expired={quote.expired}
          needsApproval={quote.needs_approval}
          hasOrder={quote.order_id !== null}
          hasPdf={quote.sent_at !== null}
          recipient={contact?.email ? { name: contactName(contact), email: contact.email } : null}
          can={{ write: canWrite, approve: canApproveQuotes(me), order: canWrite && canWriteOrders(me) }}
          act={{ submit: step("submit"), approve: step("approve"), reject: step("reject"), send: step("send"), accept: step("accept"),
                 decline: step("decline"), revise: step("revise"), order: step("order"),
                 email: emailQuote.bind(null, quote.id, quote.version) }}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">Lines</h2>
            {quote.lines.length === 0 ? (
              <p className="px-5 py-6 text-sm text-slate-600">No lines yet. Edit the quote to add products.</p>
            ) : (
              <>
                <QuoteLinesTable lines={quote.lines} currency={quote.currency} />
                <QuoteTotals quote={quote} />
              </>
            )}
          </Card>
          {(quote.customer_note || quote.internal_note) && (
            <Card className="space-y-3 p-5 text-sm">
              {quote.customer_note && <div><h3 className="font-semibold">Note for the customer</h3><p className="whitespace-pre-line text-slate-700">{quote.customer_note}</p></div>}
              {quote.internal_note && <div><h3 className="font-semibold">Internal note</h3><p className="whitespace-pre-line text-slate-700">{quote.internal_note}</p></div>}
            </Card>
          )}
        </div>
        <div className="space-y-6">
          <Card>
            <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">Details</h2>
            <dl className="space-y-3 px-5 py-4 text-sm">
              {details.map(([label, value]) => (
                <div key={label}><dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</dt><dd className="mt-0.5 text-slate-900">{value}</dd></div>
              ))}
            </dl>
          </Card>
          <Card>
            <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">History</h2>
            <ol className="divide-y divide-slate-100">
              {history.map((h, i) => (
                <li key={`${h.created_at}-${i}`} className="px-5 py-3 text-sm">
                  <p className="font-medium text-slate-900">{h.from_status === h.to_status ? "Update" : QUOTE_STATUS_LABELS[h.to_status]}</p>
                  <p className="text-xs text-slate-500">{formatDateTime(h.created_at)}{h.actor_name && ` · ${h.actor_name}`}</p>
                  {h.note && <p className="mt-0.5 text-xs text-slate-600">{h.note}</p>}
                </li>
              ))}
            </ol>
          </Card>
        </div>
      </div>
    </>
  ); // prettier-ignore
}
