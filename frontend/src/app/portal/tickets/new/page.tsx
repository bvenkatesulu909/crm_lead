import type { Metadata } from "next";
import Link from "next/link";

import { TicketForm } from "@/components/ticket-forms";
import { Card, EmptyState } from "@/components/ui";
import type { PortalAccount } from "@/lib/api-types";
import { initialFormState } from "@/lib/form-state";
import { apiFetch } from "@/lib/server/api";

import { openTicket } from "../actions";

export const metadata: Metadata = { title: "New ticket" };

export default async function NewPortalTicketPage({
  searchParams,
}: PageProps<"/portal/tickets/new">) {
  // Only the customer's own accounts are offered - and the API checks again on submit.
  const accounts = await apiFetch<PortalAccount[]>("/portal/accounts?limit=50");
  const accountParam = (await searchParams).account;

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link
          href="/portal/tickets"
          className="font-medium text-brand-700 hover:underline"
        >
          ← Support tickets
        </Link>
      </nav>
      <h1 className="mb-6 text-2xl font-semibold tracking-tight text-slate-900">
        Open a support ticket
      </h1>
      <Card className="max-w-3xl p-6">
        {accounts.length === 0 ? (
          <EmptyState
            title="No account is linked to you"
            description="Please contact your account manager to get access."
          />
        ) : (
          <TicketForm
            action={openTicket}
            initialState={initialFormState}
            accounts={accounts.map((a) => ({ id: a.id, name: a.name }))}
            defaultAccountId={
              typeof accountParam === "string" ? accountParam : undefined
            }
            cancelHref="/portal/tickets"
          />
        )}
      </Card>
    </>
  );
}
