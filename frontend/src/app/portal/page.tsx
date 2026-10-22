import type { Metadata } from "next";
import Link from "next/link";

import { PortalInvoiceList } from "@/components/invoices";
import { formatAmounts } from "@/lib/dashboard";
import { quoteNumber } from "@/lib/quotes";
import { formatDate } from "@/lib/format";
import { PortalOrderList } from "@/components/orders";
import { TicketStatusBadge, ticketNumber } from "@/components/tickets";
import {
  AccountStatus,
  ButtonLink,
  Card,
  EmptyState,
  ErrorAlert,
} from "@/components/ui";
import { toErrorInfo } from "@/lib/api-error";
import type {
  PortalAccount,
  PortalInvoiceSummary,
  PortalOrderSummary,
  PortalQuotePage,
  PortalTicket,
} from "@/lib/api-types";
import { apiFetch, getMe } from "@/lib/server/api";

export const metadata: Metadata = { title: "Customer portal" };

export default async function PortalHome() {
  const me = await getMe();
  const firstName = (me.display_name ?? "").split(" ")[0];

  let accounts: PortalAccount[] | null = null;
  let tickets: PortalTicket[] = [];
  let orders: PortalOrderSummary[] = [];
  let invoices: PortalInvoiceSummary[] = [];
  let quotes: PortalQuotePage["items"] = [];
  let failure = null;
  try {
    // The API returns ONLY the accounts (and their tickets) this customer has been granted.
    [accounts, tickets, orders, invoices, quotes] = await Promise.all([
      apiFetch<PortalAccount[]>("/portal/accounts?limit=50"),
      apiFetch<PortalTicket[]>("/portal/tickets?limit=5"),
      apiFetch<PortalOrderSummary[]>("/portal/orders?limit=5"),
      apiFetch<PortalInvoiceSummary[]>("/portal/invoices?state=unpaid&limit=5"),
      // Quotes waiting for an answer come first; the full list is on the Quotes page.
      apiFetch<PortalQuotePage>("/portal/quotes")
        .then((page) =>
          page.items.filter((q) => q.status === "sent").slice(0, 5),
        )
        .catch(() => []),
    ]);
  } catch (error) {
    failure = toErrorInfo(error);
  }

  return (
    <>
      <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
        {firstName ? `Welcome, ${firstName}` : "Welcome"}
      </h1>
      <p className="mt-1 text-sm text-slate-600">
        Your company&apos;s accounts and services.
      </p>
      <div className="mt-4">
        <ButtonLink href="/portal/knowledge" variant="secondary">
          Ask about policies &amp; help
        </ButtonLink>
      </div>

      <section aria-labelledby="accounts-heading" className="mt-8">
        <h2
          id="accounts-heading"
          className="mb-3 text-lg font-semibold text-slate-900"
        >
          Your accounts
        </h2>
        {failure ? (
          <ErrorAlert
            title="Your accounts could not be loaded"
            error={failure}
          />
        ) : accounts && accounts.length > 0 ? (
          <ul className="grid gap-4 sm:grid-cols-2">
            {accounts.map((account) => (
              <li key={account.id}>
                <Link
                  href={`/portal/accounts/${account.id}`}
                  className="block rounded-lg bg-white p-5 shadow-sm ring-1 ring-slate-200 transition hover:shadow-md hover:ring-brand-600"
                >
                  <div className="flex items-start justify-between gap-3">
                    <span className="font-semibold text-slate-900">
                      {account.name}
                    </span>
                    <AccountStatus status={account.status} />
                  </div>
                  <span className="mt-3 block text-xs font-medium text-brand-700">
                    View account →
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <Card>
            <EmptyState
              title="No accounts are linked to you yet"
              description="Please contact your account manager if you expected to see your company here."
            />
          </Card>
        )}
      </section>

      <section aria-labelledby="quotes-heading" className="mt-10">
        <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
          <h2
            id="quotes-heading"
            className="text-lg font-semibold text-slate-900"
          >
            Quotes waiting for your answer
          </h2>
          <ButtonLink href="/portal/quotes" variant="secondary">
            All quotes
          </ButtonLink>
        </div>
        <Card>
          {quotes.length === 0 ? (
            <p className="px-5 py-4 text-sm text-slate-600">No open quotes.</p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {quotes.map((q) => (
                <li
                  key={q.id}
                  className="flex flex-wrap items-center justify-between gap-3 px-5 py-3"
                >
                  <Link
                    href={`/portal/quotes/${q.id}`}
                    className="font-medium text-brand-700 hover:underline"
                  >
                    {quoteNumber(q.number, q.revision)} · {q.title}
                  </Link>
                  <span className="text-sm text-slate-600">
                    {formatAmounts([{ currency: q.currency, amount: q.total }])}{" "}
                    · valid until {formatDate(q.valid_until)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </section>

      <section aria-labelledby="orders-heading" className="mt-10">
        <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
          <h2
            id="orders-heading"
            className="text-lg font-semibold text-slate-900"
          >
            Orders
          </h2>
          <ButtonLink href="/portal/orders" variant="secondary">
            All orders
          </ButtonLink>
        </div>
        <Card>
          <PortalOrderList
            orders={orders}
            emptyText="No orders yet. Orders appear here as soon as we confirm them."
          />
        </Card>
      </section>

      <section aria-labelledby="invoices-heading" className="mt-10">
        <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
          <h2
            id="invoices-heading"
            className="text-lg font-semibold text-slate-900"
          >
            Invoices to pay
          </h2>
          <ButtonLink href="/portal/invoices" variant="secondary">
            All invoices
          </ButtonLink>
        </div>
        <Card>
          <PortalInvoiceList
            invoices={invoices}
            emptyText="Nothing to pay right now."
          />
        </Card>
      </section>

      <section aria-labelledby="support-heading" className="mt-10">
        <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
          <h2
            id="support-heading"
            className="text-lg font-semibold text-slate-900"
          >
            Support
          </h2>
          <div className="flex gap-2">
            <ButtonLink href="/portal/tickets" variant="secondary">
              All tickets
            </ButtonLink>
            {accounts && accounts.length > 0 && (
              <ButtonLink href="/portal/tickets/new">New ticket</ButtonLink>
            )}
          </div>
        </div>
        <Card>
          {tickets.length === 0 ? (
            <p className="px-5 py-6 text-sm text-slate-600">
              No support tickets. If something isn&apos;t working, open a
              ticket.
            </p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {tickets.map((t) => (
                <li
                  key={t.id}
                  className="flex flex-wrap items-center justify-between gap-3 px-5 py-3"
                >
                  <Link
                    href={`/portal/tickets/${t.id}`}
                    className="text-sm font-medium text-brand-700 hover:underline"
                  >
                    <span className="font-mono text-xs text-slate-500">
                      {ticketNumber(t.number)}
                    </span>{" "}
                    {t.subject}
                  </Link>
                  <TicketStatusBadge status={t.status} portal />
                </li>
              ))}
            </ul>
          )}
        </Card>
      </section>

      <section aria-labelledby="assistant-heading" className="mt-10">
        <h2
          id="assistant-heading"
          className="mb-3 text-lg font-semibold text-slate-900"
        >
          Assistant
        </h2>
        <Card className="flex flex-wrap items-center justify-between gap-4 p-5">
          <p className="text-sm text-slate-600">
            Questions about your orders, invoices or tickets? Ask our AI
            assistant - it only sees your company&apos;s data and hands over to
            our team when needed.
          </p>
          <ButtonLink href="/portal/assistant">Ask the assistant</ButtonLink>
        </Card>
      </section>
    </>
  );
}
