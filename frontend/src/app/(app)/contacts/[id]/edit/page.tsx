import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ContactForm } from "@/components/customer-forms";
import { Card, Forbidden, PageHeader } from "@/components/ui";
import { ApiError } from "@/lib/api-error";
import type { Contact } from "@/lib/api-types";
import { contactName } from "@/lib/customer-data";
import { initialFormState } from "@/lib/form-state";
import { canManageContacts, canWriteContacts } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";
import { accountOptions, salesOwnerOptions } from "@/lib/server/options";

import { updateContact } from "../../actions";

export const metadata: Metadata = { title: "Edit contact" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function EditContactPage({
  params,
}: PageProps<"/contacts/[id]/edit">) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  const me = await getMe();
  if (!canWriteContacts(me)) return <Forbidden />;
  let contact: Contact;
  try {
    contact = await apiFetch<Contact>(`/contacts/${id}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
  const manager = canManageContacts(me);
  const [accounts, owners] = await Promise.all([
    accountOptions(),
    manager ? salesOwnerOptions() : Promise.resolve(undefined),
  ]);
  // Keep the current account selectable even if it isn't in this user's account list.
  if (contact.account_id && !accounts.some((a) => a.id === contact.account_id))
    accounts.unshift({ id: contact.account_id, name: "Current account" });

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link
          href={`/contacts/${contact.id}`}
          className="font-medium text-brand-700 hover:underline"
        >
          ← {contactName(contact)}
        </Link>
      </nav>
      <PageHeader title="Edit contact" description={contactName(contact)} />
      <Card className="max-w-3xl p-6">
        <ContactForm
          action={updateContact.bind(null, contact.id, contact.version)}
          initialState={initialFormState}
          contact={contact}
          accounts={accounts}
          owners={owners}
          cancelHref={`/contacts/${contact.id}`}
          submitLabel="Save changes"
        />
      </Card>
    </>
  );
}
