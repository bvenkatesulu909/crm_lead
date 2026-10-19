import type { Metadata } from "next";
import Link from "next/link";

import { TicketStatusBadge, ticketNumber } from "@/components/tickets";
import { ButtonLink, Card, EmptyState, ErrorAlert } from "@/components/ui";
import { toErrorInfo } from "@/lib/api-error";
import type { PortalAccount, PortalTicket } from "@/lib/api-types";
import { formatDate } from "@/lib/format";
import { apiFetch } from "@/lib/server/api";

export const metadata: Metadata = { title: "Support tickets" };

export default async function PortalTicketsPage() {
  let tickets: PortalTicket[];
  let accounts: PortalAccount[];
  try {
    [tickets, accounts] = await Promise.all([
      apiFetch<PortalTicket[]>("/portal/tickets?limit=100"),
      apiFetch<PortalAccount[]>("/portal/accounts?limit=50"),
    ]);
  } catch (error) {
    return (
      <ErrorAlert
        title="Your tickets could not be loaded"
        error={toErrorInfo(error)}
      />
    );
  }
  const accountName = (id: string) =>
    accounts.find((a) => a.id === id)?.name ?? "";

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link href="/portal" className="font-medium text-brand-700 hover:underline">
          ← Portal home
        </Link>
      </nav>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Support tickets</h1>
          <p className="mt-1 text-sm text-slate-600">Requests from your company and their progress.</p>
        </div>
        {accounts.length > 0 && <ButtonLink href="/portal/tickets/new">New ticket</ButtonLink>}
      </div>
      <Card>
        {tickets.length === 0 ? (
          <EmptyState
            title="No tickets yet"
            description="If something isn't working, open a ticket and our support team will help."
            action={accounts.length > 0 && <ButtonLink href="/portal/tickets/new">Open a ticket</ButtonLink>}
          />
        ) : (
          <ul className="divide-y divide-slate-100">
            {tickets.map((t) => (
              <li key={t.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
                <div className="min-w-0">
                  <Link href={`/portal/tickets/${t.id}`} className="font-medium text-brand-700 hover:underline">
                    <span className="font-mono text-xs text-slate-500">{ticketNumber(t.number)}</span> {t.subject}
                  </Link>
                  <p className="text-xs text-slate-500">
                    {accountName(t.account_id)} · opened {formatDate(t.created_at)}
                  </p>
                </div>
                <TicketStatusBadge status={t.status} portal />
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  ); // prettier-ignore
}
