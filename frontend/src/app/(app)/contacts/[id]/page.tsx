import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { ActivityPanel } from "@/components/activity-panel";
import { EmailCard } from "@/components/email-card";
import { Card, Forbidden, SuccessAlert } from "@/components/ui";
import { ApiError } from "@/lib/api-error";
import type {
  Account,
  Contact,
  DirectoryUser,
  TimelineEntry,
} from "@/lib/api-types";
import {
  CHANNEL_LABELS,
  CONSENT_LABELS,
  contactName,
  describeChanges,
} from "@/lib/customer-data";
import { formatDateTime } from "@/lib/format";
import { canManageContacts, canWriteContacts } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import { archiveContact } from "../actions";
import { ContactActions } from "./contact-actions";

export const metadata: Metadata = { title: "Contact" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const DONE: Record<string, string> = {
  "email-sent": "The e-mail is on its way. Its status is shown under E-mails.",
  "email-logged": "The received e-mail was saved in the history.",
  created: "The contact was created.",
  updated: "Your changes were saved.",
  planned: "The task was added.",
  logged: "The interaction was logged.",
  completed: "The task was marked as done.",
  cancelled: "The task was cancelled.",
  reopened: "The task is open again.",
};

async function loadContact(id: string): Promise<Contact | "forbidden"> {
  if (!UUID.test(id)) notFound();
  try {
    return await apiFetch<Contact>(`/contacts/${id}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    if (error instanceof ApiError && error.status === 403) return "forbidden";
    throw error;
  }
}

export default async function ContactPage({
  params,
  searchParams,
}: PageProps<"/contacts/[id]">) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  const done = typeof query.done === "string" ? DONE[query.done] : undefined;
  const [contact, me] = await Promise.all([loadContact(id), getMe()]);
  if (contact === "forbidden") return <Forbidden />;

  const [account, people, history] = await Promise.all([
    contact.account_id
      ? apiFetch<Account>(`/accounts/${contact.account_id}`).catch(() => null)
      : Promise.resolve(null),
    apiFetch<DirectoryUser[]>("/users").catch(() => []),
    apiFetch<TimelineEntry[]>(`/contacts/${contact.id}/history`).catch(
      () => [],
    ),
  ]);
  // Display only - same rule as the API: your contacts and the people at your accounts.
  const mayEdit =
    canWriteContacts(me) &&
    (canManageContacts(me) ||
      contact.owner_id === me.user_id ||
      account?.owner_id === me.user_id);
  const owner =
    contact.owner_id === null
      ? "Nobody"
      : (people.find((p) => p.id === contact.owner_id)?.display_name ??
        "Former colleague");
  const mail = contact.email ? (
    <a
      href={`mailto:${contact.email}`}
      className="text-brand-700 hover:underline"
    >
      {contact.email}
    </a>
  ) : (
    "—"
  );

  const groups: [string, [string, ReactNode][]][] = [
    ["Person", [
      ["Designation", contact.job_title ?? "—"],
      ["Department", contact.department ?? "—"],
      ["Account", account ? (
        <Link href={`/accounts/${account.id}`} className="text-brand-700 hover:underline">{account.name}</Link>
      ) : contact.account_id ? "Not visible to you" : "No account"],
      ["Primary contact", contact.is_primary ? "Yes" : "No"],
      ["Owner", owner],
    ]],
    ["Communication", [
      ["E-mail", mail],
      ["Phone", contact.phone ?? "—"],
      ["Mobile", contact.mobile ?? "—"],
    ]],
    ["Preferences and consent", [
      ["Preferred channel", contact.preferred_channel ? CHANNEL_LABELS[contact.preferred_channel] : "—"],
      ["Marketing e-mails", `${CONSENT_LABELS[contact.email_consent]}${contact.email_consent_at ? ` (since ${formatDateTime(contact.email_consent_at)})` : ""}`],
      ["Calls", contact.do_not_call ? "Do not call" : "Calls are fine"],
    ]],
  ]; // prettier-ignore

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link href="/contacts" className="font-medium text-brand-700 hover:underline">← Contacts</Link>
      </nav>
      {done && <div className="mb-4"><SuccessAlert>{done}</SuccessAlert></div>}
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{contactName(contact)}</h1>
            {contact.is_primary && (
              <span className="rounded-full bg-brand-50 px-2.5 py-0.5 text-xs font-medium text-brand-700">Primary contact</span>
            )}
            {contact.do_not_call && (
              <span className="rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-medium text-amber-800">Do not call</span>
            )}
          </div>
          <p className="mt-1 text-sm text-slate-600">
            {[contact.job_title, account?.name].filter(Boolean).join(" at ") || "No designation"}
          </p>
        </div>
        {mayEdit && (
          <ContactActions
            contactId={contact.id}
            archive={archiveContact.bind(null, contact.id, contact.version, contact.account_id)}
          />
        )}
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          {groups.map(([title, rows]) => (
            <Card key={title}>
              <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">{title}</h2>
              <dl className="grid gap-x-6 gap-y-4 px-5 py-4 sm:grid-cols-2">
                {rows.map(([label, value]) => (
                  <div key={label}>
                    <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</dt>
                    <dd className="mt-1 break-words text-sm text-slate-900">{value}</dd>
                  </div>
                ))}
              </dl>
            </Card>
          ))}
          <ActivityPanel
            link={{ type: "contact", id: contact.id }}
            me={me}
            people={people}
            ownsRecord={contact.owner_id === me.user_id || account?.owner_id === me.user_id}
          />
          <EmailCard
            me={me}
            record={{ type: "contact", id: contact.id }}
            person={{ email: contact.email, email_consent: contact.email_consent }}
            personLabel={contactName(contact)}
          />
        </div>
        <Card>
          <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">History</h2>
          {history.length === 0 ? (
            <p className="px-5 py-6 text-sm text-slate-600">No recorded changes.</p>
          ) : (
            <ol className="divide-y divide-slate-100">
              {history.map((h, index) => (
                <li key={`${h.at}-${index}`} className="px-5 py-3">
                  <p className="text-sm font-medium text-slate-900">{h.title}</p>
                  <p className="text-xs text-slate-500">
                    {formatDateTime(h.at)}
                    {h.actor_name && ` · ${h.actor_name}`}
                  </p>
                  <ul className="mt-1 space-y-0.5 text-xs text-slate-600">
                    {describeChanges(h).map((line) => <li key={line}>{line}</li>)}
                  </ul>
                </li>
              ))}
            </ol>
          )}
          
        </Card>
      </div>
    </>
  ); // prettier-ignore
}
