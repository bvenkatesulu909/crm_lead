import type { Metadata } from "next";

import { ContactForm } from "@/components/customer-forms";
import { Card, Forbidden, PageHeader } from "@/components/ui";
import { initialFormState } from "@/lib/form-state";
import { canManageContacts, canWriteContacts } from "@/lib/permissions";
import { getMe } from "@/lib/server/api";
import { accountOption, salesOwnerOptions } from "@/lib/server/options";

import { createContact } from "../actions";

export const metadata: Metadata = { title: "New contact" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function NewContactPage({
  searchParams,
}: PageProps<"/contacts/new">) {
  const { account } = await searchParams;
  const me = await getMe();
  // Friendly early answer; the API would refuse anyway.
  if (!canWriteContacts(me)) return <Forbidden />;
  const manager = canManageContacts(me);
  const [defaultAccount, owners] = await Promise.all([
    accountOption(account),
    manager ? salesOwnerOptions() : Promise.resolve(undefined),
  ]);
  const fromAccount =
    typeof account === "string" && UUID.test(account) ? account : undefined;

  return (
    <>
      <PageHeader
        title="New contact"
        description="A person you work with at a customer."
      />
      <Card className="max-w-3xl p-6">
        <ContactForm
          action={createContact}
          initialState={initialFormState}
          defaultAccount={defaultAccount}
          owners={owners}
          cancelHref={fromAccount ? `/accounts/${fromAccount}` : "/contacts"}
          submitLabel="Create contact"
        />
      </Card>
    </>
  );
}
