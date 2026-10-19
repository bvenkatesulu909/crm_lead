import type { Metadata } from "next";
import Link from "next/link";

import { Pagination } from "@/components/pagination";
import {
  ButtonLink,
  Card,
  EmptyState,
  ErrorAlert,
  Forbidden,
  PageHeader,
  SuccessAlert,
  buttonClass,
} from "@/components/ui";
import { ApiError, toErrorInfo } from "@/lib/api-error";
import {
  EMAIL_CONSENTS,
  type AccountPage,
  type ContactPage,
} from "@/lib/api-types";
import { CONSENT_LABELS, contactName } from "@/lib/customer-data";
import { canWriteContacts, hasAny } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import {
  CONTACT_PAGE_SIZE,
  contactApiQuery,
  contactPageHref,
  parseContactParams,
} from "./list-params";

export const metadata: Metadata = { title: "Contacts" };

const field =
  "mt-1 block w-full rounded-md border-0 bg-white px-3 py-2 text-sm text-slate-900 ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-brand-600";

export default async function ContactsPage({
  searchParams,
}: PageProps<"/contacts">) {
  const raw = await searchParams;
  const p = parseContactParams(raw);
  const me = await getMe();

  let data: ContactPage;
  let accounts: AccountPage["items"];
  try {
    [data, accounts] = await Promise.all([
      apiFetch<ContactPage>(`/contacts?${contactApiQuery(p)}`),
      apiFetch<AccountPage>("/accounts?limit=200")
        .then((a) => a.items)
        .catch(() => []),
    ]);
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) return <Forbidden />;
    return (
      <>
        <PageHeader title="Contacts" />
        <ErrorAlert
          title="Contacts could not be loaded"
          error={toErrorInfo(error)}
        />
      </>
    );
  }
  const accountName = (id: string | null) =>
    id === null
      ? "—"
      : (accounts.find((a) => a.id === id)?.name ?? "Not visible to you");
  const filtered = Boolean(p.q || p.consent);

  return (
    <>
      <PageHeader
        title="Contacts"
        description={
          hasAny(me, "contact:read:all")
            ? "All contacts of your organisation."
            : "Your contacts and the people at your accounts."
        }
        actions={
          canWriteContacts(me) && (
            <ButtonLink href="/contacts/new">New contact</ButtonLink>
          )
        }
      />
      {raw.done === "archived" && (
        <div className="mb-4">
          <SuccessAlert>The contact was archived.</SuccessAlert>
        </div>
      )}
      <Card>
        <form
          role="search"
          aria-label="Filter contacts"
          className="grid gap-4 px-5 py-4 sm:grid-cols-[2fr_1fr_auto]"
        >
          <div>
            <label htmlFor="contact-q" className="text-sm font-medium text-slate-700">
              Search
            </label>
            <input id="contact-q" name="q" type="search" defaultValue={p.q} maxLength={100}
              placeholder="Name, e-mail, phone or designation" className={field} />
          </div>
          <div>
            <label htmlFor="contact-consent-filter" className="text-sm font-medium text-slate-700">
              E-mail consent
            </label>
            <select id="contact-consent-filter" name="consent" defaultValue={p.consent} className={field}>
              <option value="">Any</option>
              {EMAIL_CONSENTS.map((c) => <option key={c} value={c}>{CONSENT_LABELS[c]}</option>)}
            </select>
          </div>
          <div className="flex items-end gap-2">
            <button type="submit" className={buttonClass("primary")}>Apply</button>
            {filtered && <Link href="/contacts" className={buttonClass("secondary")}>Clear</Link>}
          </div>
        </form>
        <div className="border-t border-slate-200">
          {data.items.length === 0 ? (
            <EmptyState
              title={filtered ? "No contacts match your search" : "No contacts yet"}
              description={filtered ? "Try other words or remove the filter." : "Add the people you work with at your customers."}
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200 text-sm">
                <caption className="sr-only">Contacts, page {p.page}</caption>
                <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-600">
                  <tr>
                    <th scope="col" className="px-5 py-3">Name</th>
                    <th scope="col" className="hidden px-5 py-3 md:table-cell">Designation</th>
                    <th scope="col" className="px-5 py-3">Account</th>
                    <th scope="col" className="hidden px-5 py-3 lg:table-cell">E-mail / phone</th>
                    <th scope="col" className="hidden px-5 py-3 sm:table-cell">Consent</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {data.items.map((c) => (
                    <tr key={c.id} className="hover:bg-slate-50">
                      <th scope="row" className="px-5 py-3 text-left font-medium">
                        <Link href={`/contacts/${c.id}`} className="text-brand-700 hover:underline">{contactName(c)}</Link>
                        {c.is_primary && <span className="ml-2 rounded-full bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-700">Primary</span>}
                      </th>
                      <td className="hidden px-5 py-3 text-slate-700 md:table-cell">{c.job_title ?? "—"}</td>
                      <td className="px-5 py-3 text-slate-700">
                        {c.account_id ? (
                          <Link href={`/accounts/${c.account_id}`} className="hover:underline">{accountName(c.account_id)}</Link>
                        ) : "—"}
                      </td>
                      <td className="hidden px-5 py-3 text-slate-700 lg:table-cell">
                        {[c.email, c.phone ?? c.mobile].filter(Boolean).join(" · ") || "—"}
                      </td>
                      <td className="hidden px-5 py-3 text-slate-700 sm:table-cell">{CONSENT_LABELS[c.email_consent]}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        {data.total > 0 && (
          <div className="border-t border-slate-200">
            <Pagination total={data.total} page={p.page} pageSize={CONTACT_PAGE_SIZE} hrefForPage={(page) => contactPageHref(p, page)} />
          </div>
        )}
      </Card>
    </>
  ); // prettier-ignore
}
