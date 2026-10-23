import type { Metadata } from "next";

import { TicketForm } from "@/components/ticket-forms";
import { Card, Forbidden, PageHeader } from "@/components/ui";
import type { Account } from "@/lib/api-types";
import { initialFormState } from "@/lib/form-state";
import { canManageTickets } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import { createTicket } from "../actions";

export const metadata: Metadata = { title: "New ticket" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Staff open a ticket on behalf of a customer (e.g. after a phone call). */
export default async function NewTicketPage({
  searchParams,
}: PageProps<"/tickets/new">) {
  const me = await getMe();
  if (!canManageTickets(me)) return <Forbidden />;
  const accountParam = (await searchParams).account;
  // "New ticket" on an account page links here with ?account=<id>: show that account as chosen.
  // The API decides whether the user may see it; if not, the field simply starts empty.
  let defaultAccount: { id: string; name: string } | null = null;
  if (typeof accountParam === "string" && UUID.test(accountParam)) {
    try {
      const account = await apiFetch<Account>(`/accounts/${accountParam}`);
      defaultAccount = { id: account.id, name: account.name };
    } catch {
      defaultAccount = null;
    }
  }

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
          accounts={[]}
          searchAccounts
          defaultAccount={defaultAccount}
          withPriority
          cancelHref="/tickets"
          submitLabel="Create ticket"
        />
      </Card>
    </>
  );
}
