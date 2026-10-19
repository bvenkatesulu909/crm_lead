import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { PortalInvoiceList } from "@/components/invoices";
import { PortalOrderList } from "@/components/orders";
import { TicketStatusBadge, ticketNumber } from "@/components/tickets";
import { AccountStatus, ButtonLink, Card } from "@/components/ui";
import { ApiError } from "@/lib/api-error";
import type {
  PortalAccount,
  PortalDocument,
  PortalInvoiceSummary,
  PortalOrderSummary,
  PortalTicket,
} from "@/lib/api-types";
import { formatBytes, formatDate } from "@/lib/format";
import { apiFetch } from "@/lib/server/api";

export const metadata: Metadata = { title: "Account" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * One of the customer's own accounts. Another customer's account (same or other tenant) is
 * answered by the API with 404, exactly like an account that doesn't exist.
 */
export default async function PortalAccountPage({
  params,
}: PageProps<"/portal/accounts/[id]">) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  let account: PortalAccount;
  let tickets: PortalTicket[];
  let orders: PortalOrderSummary[];
  let invoices: PortalInvoiceSummary[];
  let documents: PortalDocument[];
  try {
    [account, tickets, orders, invoices, documents] = await Promise.all([
      apiFetch<PortalAccount>(`/portal/accounts/${id}`),
      apiFetch<PortalTicket[]>(`/portal/tickets?account_id=${id}&limit=50`),
      apiFetch<PortalOrderSummary[]>(
        `/portal/orders?account_id=${id}&limit=50`,
      ),
      apiFetch<PortalInvoiceSummary[]>(
        `/portal/invoices?account_id=${id}&limit=50`,
      ),
      // Only files the supplier shared with this company (newest version of each).
      apiFetch<{ items: PortalDocument[] }>(
        `/portal/documents?account_id=${id}`,
      )
        .then((d) => d.items)
        .catch(() => []),
    ]);
  } catch (error) {
    if (
      error instanceof ApiError &&
      (error.status === 404 || error.status === 403)
    )
      notFound();
    throw error;
  }
  const website =
    account.website && /^https?:\/\//.test(account.website)
      ? account.website
      : null;

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link
          href="/portal"
          className="font-medium text-brand-700 hover:underline"
        >
          ← Your accounts
        </Link>
      </nav>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
          {account.name}
        </h1>
        <AccountStatus status={account.status} />
      </div>
      {website && (
        <p className="mt-1 text-sm">
          <a
            href={website}
            rel="noopener noreferrer nofollow"
            target="_blank"
            className="text-brand-700 hover:underline"
          >
            {website}
          </a>
        </p>
      )}

      <section aria-labelledby="account-orders" className="mt-8">
        <h2
          id="account-orders"
          className="mb-3 text-lg font-semibold text-slate-900"
        >
          Orders
        </h2>
        <Card>
          <PortalOrderList
            orders={orders}
            emptyText="No orders for this account."
          />
        </Card>
      </section>

      <section aria-labelledby="account-tickets" className="mt-8">
        <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
          <h2
            id="account-tickets"
            className="text-lg font-semibold text-slate-900"
          >
            Support tickets
          </h2>
          <ButtonLink href={`/portal/tickets/new?account=${account.id}`}>
            New ticket
          </ButtonLink>
        </div>
        <Card>
          {tickets.length === 0 ? (
            <p className="px-5 py-6 text-sm text-slate-600">
              No tickets for this account.
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

      <section aria-labelledby="account-invoices" className="mt-8">
        <h2
          id="account-invoices"
          className="mb-3 text-lg font-semibold text-slate-900"
        >
          Invoices
        </h2>
        <Card>
          <PortalInvoiceList
            invoices={invoices}
            emptyText="No invoices for this account."
          />
        </Card>
      </section>

      <section aria-labelledby="account-documents" className="mt-8">
        <h2
          id="account-documents"
          className="mb-3 text-lg font-semibold text-slate-900"
        >
          Documents
        </h2>
        <Card>
          {documents.length === 0 ? (
            <p className="px-5 py-6 text-sm text-slate-600">
              No documents have been shared with you yet.
            </p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {documents.map((d) => (
                <li
                  key={d.id}
                  className="flex items-center justify-between gap-3 px-5 py-3"
                >
                  <a
                    href={`/portal/documents/${d.id}/download`}
                    download
                    className="break-all text-sm font-medium text-brand-700 hover:underline"
                  >
                    {d.file_name}
                  </a>
                  <span className="shrink-0 text-xs text-slate-500">
                    {formatBytes(d.size_bytes)} · {formatDate(d.created_at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </section>
    </>
  );
}
