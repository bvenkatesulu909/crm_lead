import type { Metadata } from "next";

import { TicketForm } from "@/components/ticket-forms";
import { Card, Forbidden, PageHeader } from "@/components/ui";
import type { AccountPage } from "@/lib/api-types";
import { initialFormState } from "@/lib/form-state";
import { canManageTickets } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import { createTicket } from "../actions";

export const metadata: Metadata = { title: "New ticket" };

/** Staff open a ticket on behalf of a customer (e.g. after a phone call). */
export default async function NewTicketPage({
  searchParams,
}: PageProps<"/tickets/new">) {
  const me = await getMe();
  if (!canManageTickets(me)) return <Forbidden />;
  const accounts = (await apiFetch<AccountPage>("/accounts?limit=200")).items;
  const accountParam = (await searchParams).account;

  return (
    <>
      <PageHeader
        title="New ticket"
        description="Record a customer's request, for example after a phone call."
      />
      <Card className="max-w-3xl p-6">
        <TicketForm
          action={createTicket}
          initialState={initialFormState}
          accounts={accounts.map((a) => ({ id: a.id, name: a.name }))}
          defaultAccountId={
            typeof accountParam === "string" ? accountParam : undefined
          }
          withPriority
          cancelHref="/tickets"
          submitLabel="Create ticket"
        />
      </Card>
    </>
  );
}
