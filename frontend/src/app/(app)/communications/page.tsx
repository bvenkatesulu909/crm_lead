import type { Metadata } from "next";
import Link from "next/link";

import { EmailStatusBadge } from "@/components/email-views";
import { Pagination } from "@/components/pagination";
import {
  ButtonLink,
  Card,
  EmptyState,
  ErrorAlert,
  Forbidden,
  PageHeader,
  buttonClass,
} from "@/components/ui";
import { ApiError, toErrorInfo } from "@/lib/api-error";
import {
  EMAIL_DIRECTIONS,
  EMAIL_STATUSES,
  type EmailPage,
} from "@/lib/api-types";
import {
  EMAIL_DIRECTION_LABELS,
  EMAIL_STATUS_LABELS,
  emailPageHref,
  emailQuery,
  failureText,
  messageRecordHref,
  parseEmailFilters,
} from "@/lib/communications";
import { formatDateTime } from "@/lib/format";
import {
  canManageEmailTemplates,
  canReadEmailCenter,
  hasAny,
} from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

export const metadata: Metadata = { title: "Communication Center" };

const PAGE_SIZE = 25;
const field =
  "mt-1 block w-full rounded-md border-0 bg-white px-3 py-2 text-sm text-slate-900 ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-brand-600";

/**
 * The Communication Center: e-mails sent from the CRM and received e-mails logged by hand.
 * Managers see every e-mail of the organisation, agents the ones they wrote or logged - the
 * API filters this in the database. E-mails are written from a lead, contact, account or deal.
 */
export default async function CommunicationsPage({
  searchParams,
}: PageProps<"/communications">) {
  const filters = parseEmailFilters(await searchParams);
  const me = await getMe();
  if (!canReadEmailCenter(me)) return <Forbidden />;

  let data: EmailPage;
  try {
    data = await apiFetch<EmailPage>(`/communications/emails?${emailQuery(filters, PAGE_SIZE)}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) return <Forbidden />;
    return <ErrorAlert title="E-mails could not be loaded" error={toErrorInfo(error)} />;
  }
  const filtered = filters.q || filters.status || filters.direction;
  const everyone = hasAny(me, "communication:read:all");

  return (
    <>
      <PageHeader
        title="Communication Center"
        description={everyone ? "Every e-mail of your organisation, sent from the CRM or logged by hand." : "The e-mails you sent from the CRM or logged by hand."}
        actions={canManageEmailTemplates(me) && <ButtonLink href="/communications/templates" variant="secondary">Templates</ButtonLink>}
      />
      <p className="mb-4 text-sm text-slate-600">
        To write an e-mail, open a lead, contact, account or deal and use <span className="font-medium">Send e-mail</span>.
      </p>
      <Card>
        <form role="search" aria-label="Filter e-mails" className="grid gap-4 px-5 py-4 sm:grid-cols-[2fr_1fr_1fr_auto]">
          <div>
            <label htmlFor="email-q" className="text-sm font-medium text-slate-700">Search</label>
            <input id="email-q" name="q" type="search" defaultValue={filters.q} maxLength={100} placeholder="Subject" className={field} />
          </div>
          <div>
            <label htmlFor="email-status" className="text-sm font-medium text-slate-700">Status</label>
            <select id="email-status" name="status" defaultValue={filters.status} className={field}>
              <option value="">All statuses</option>
              {EMAIL_STATUSES.map((s) => <option key={s} value={s}>{EMAIL_STATUS_LABELS[s]}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="email-direction" className="text-sm font-medium text-slate-700">Direction</label>
            <select id="email-direction" name="direction" defaultValue={filters.direction} className={field}>
              <option value="">Sent and received</option>
              {EMAIL_DIRECTIONS.map((d) => <option key={d} value={d}>{EMAIL_DIRECTION_LABELS[d]}</option>)}
            </select>
          </div>
          <div className="flex items-end gap-2">
            <button type="submit" className={buttonClass("primary")}>Apply</button>
            {filtered && <Link href="/communications" className={buttonClass("secondary")}>Clear</Link>}
          </div>
        </form>
        <div className="border-t border-slate-200">
          {data.items.length === 0 ? (
            <EmptyState
              title={filtered ? "No e-mails match" : "No e-mails yet"}
              description={filtered ? "Try other filters." : "E-mails you send from a lead, contact, account or deal appear here."}
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200 text-sm">
                <caption className="sr-only">E-mails, page {filters.page}</caption>
                <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-600">
                  <tr>
                    <th scope="col" className="px-5 py-3">Subject</th>
                    <th scope="col" className="px-5 py-3">With</th>
                    <th scope="col" className="px-5 py-3">Status</th>
                    <th scope="col" className="hidden px-5 py-3 md:table-cell">When</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {data.items.map((m) => {
                    const href = messageRecordHref(m);
                    return (
                      <tr key={m.id}>
                        <th scope="row" className="px-5 py-3 text-left font-medium text-slate-900">
                          <span className="mr-2 text-xs font-normal text-slate-500">{m.direction === "outbound" ? "To" : "From"}</span>
                          {m.subject}
                          {m.status === "failed" && <p className="mt-0.5 text-xs font-normal text-red-700">{failureText(m.error_code)}</p>}
                        </th>
                        <td className="px-5 py-3 text-slate-700">
                          {href ? <Link href={href} className="text-brand-700 hover:underline">{m.to_address}</Link> : m.to_address}
                        </td>
                        <td className="px-5 py-3"><EmailStatusBadge status={m.status} /></td>
                        <td className="hidden px-5 py-3 whitespace-nowrap text-slate-700 md:table-cell">{formatDateTime(m.sent_at ?? m.created_at)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
        {data.total > 0 && (
          <div className="border-t border-slate-200">
            <Pagination total={data.total} page={filters.page} pageSize={PAGE_SIZE} hrefForPage={(p) => emailPageHref(filters, p)} />
          </div>
        )}
      </Card>
    </>
  ); // prettier-ignore
}
