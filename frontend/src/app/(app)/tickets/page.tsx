import type { Metadata } from "next";
import Link from "next/link";

import { Pagination } from "@/components/pagination";
import {
  CATEGORY_LABELS,
  CategoryBadge,
  PRIORITY_LABELS,
  PriorityBadge,
  SlaBadge,
  TICKET_STATUS_LABELS,
  TicketStatusBadge,
  ticketNumber,
} from "@/components/tickets";
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
  TICKET_CATEGORIES,
  TICKET_PRIORITIES,
  TICKET_STATUSES,
  type AccountPage,
  type DirectoryUser,
  type TicketPage,
} from "@/lib/api-types";
import { formatDate } from "@/lib/format";
import { canManageTickets, canReadAccounts, hasAny } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

export const metadata: Metadata = { title: "Support" };

const PAGE_SIZE = 20;
const field =
  "mt-1 block w-full rounded-md border-0 bg-white px-3 py-2 text-sm text-slate-900 ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-brand-600";

type Raw = Record<string, string | string[] | undefined>;
const one = (v: string | string[] | undefined) =>
  (Array.isArray(v) ? v[0] : v) ?? "";

function parse(raw: Raw) {
  const status = one(raw.status);
  const priority = one(raw.priority);
  const category = one(raw.category);
  const view = one(raw.view);
  const page = Number.parseInt(one(raw.page), 10);
  return {
    q: one(raw.q).trim().slice(0, 100),
    status: (TICKET_STATUSES as readonly string[]).includes(status)
      ? status
      : "",
    priority: (TICKET_PRIORITIES as readonly string[]).includes(priority)
      ? priority
      : "",
    category: (TICKET_CATEGORIES as readonly string[]).includes(category)
      ? category
      : "",
    view: ["mine", "unassigned", "overdue"].includes(view) ? view : "",
    page: Number.isFinite(page) && page > 0 && page <= 5000 ? page : 1,
  };
}
type Params = ReturnType<typeof parse>;

function href(p: Params, page: number) {
  const q = new URLSearchParams();
  for (const key of ["q", "status", "priority", "category", "view"] as const)
    if (p[key]) q.set(key, p[key]);
  if (page > 1) q.set("page", String(page));
  const s = q.toString();
  return s ? `/tickets?${s}` : "/tickets";
}

export default async function TicketsPage({
  searchParams,
}: PageProps<"/tickets">) {
  const p = parse(await searchParams);
  const me = await getMe();
  const query = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String((p.page - 1) * PAGE_SIZE),
  });
  if (p.q) query.set("q", p.q);
  if (p.status) query.set("status", p.status);
  else if (!p.view)
    for (const s of ["new", "open", "pending_customer"])
      query.append("status", s);
  if (p.priority) query.set("priority", p.priority);
  if (p.category) query.set("category", p.category);
  if (p.view === "mine" && me.user_id) query.set("assignee_id", me.user_id);
  if (p.view === "unassigned") query.set("unassigned", "true");
  if (p.view === "overdue") query.set("overdue", "true");

  let data: TicketPage;
  let people: DirectoryUser[];
  let accounts: AccountPage["items"] = [];
  try {
    [data, people, accounts] = await Promise.all([
      apiFetch<TicketPage>(`/tickets?${query}`),
      apiFetch<DirectoryUser[]>("/users"),
      canReadAccounts(me)
        ? apiFetch<AccountPage>("/accounts?limit=200").then((a) => a.items)
        : Promise.resolve([]),
    ]);
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) return <Forbidden />;
    return (
      <>
        <PageHeader title="Support" />
        <ErrorAlert
          title="Tickets could not be loaded"
          error={toErrorInfo(error)}
        />
      </>
    );
  }
  const personName = (id: string | null) =>
    id
      ? (people.find((u) => u.id === id)?.display_name ?? "Former colleague")
      : "Unassigned";
  const accountName = (id: string) =>
    accounts.find((a) => a.id === id)?.name ?? "Customer account";
  const filtered = Boolean(
    p.q || p.status || p.priority || p.category || p.view,
  );

  return (
    <>
      <PageHeader
        title="Support"
        description={
          hasAny(me, "ticket:read:all")
            ? "Support tickets of your organisation. Open tickets are shown unless you filter."
            : "Support tickets of the customers you own."
        }
        actions={canManageTickets(me) && <ButtonLink href="/tickets/new">New ticket</ButtonLink>}
      />
      <Card>
        <form role="search" aria-label="Filter tickets" className="grid gap-4 px-5 py-4 sm:grid-cols-2 lg:grid-cols-[2fr_1fr_1fr_1fr_auto]">
          <div>
            <label htmlFor="t-q" className="text-sm font-medium text-slate-700">Search</label>
            <input id="t-q" name="q" type="search" defaultValue={p.q} maxLength={100} placeholder="Subject or T-number" className={field} />
          </div>
          <div>
            <label htmlFor="t-status" className="text-sm font-medium text-slate-700">Status</label>
            <select id="t-status" name="status" defaultValue={p.status} className={field}>
              <option value="">Open tickets</option>
              {TICKET_STATUSES.map((s) => <option key={s} value={s}>{TICKET_STATUS_LABELS[s]}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="t-priority" className="text-sm font-medium text-slate-700">Priority</label>
            <select id="t-priority" name="priority" defaultValue={p.priority} className={field}>
              <option value="">Any priority</option>
              {TICKET_PRIORITIES.map((s) => <option key={s} value={s}>{PRIORITY_LABELS[s]}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="t-category" className="text-sm font-medium text-slate-700">Category</label>
            <select id="t-category" name="category" defaultValue={p.category} className={field}>
              <option value="">All categories</option>
              {TICKET_CATEGORIES.map((c) => <option key={c} value={c}>{CATEGORY_LABELS[c]}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="t-view" className="text-sm font-medium text-slate-700">Show</label>
            <select id="t-view" name="view" defaultValue={p.view} className={field}>
              <option value="">Everything</option>
              <option value="mine">Assigned to me</option>
              <option value="unassigned">Unassigned</option>
              <option value="overdue">SLA overdue</option>
            </select>
          </div>
          <div className="flex items-end gap-2">
            <button type="submit" className={buttonClass("primary")}>Apply</button>
            {filtered && <Link href="/tickets" className={buttonClass("secondary")}>Clear</Link>}
          </div>
        </form>
        <div className="border-t border-slate-200">
          {data.items.length === 0 ? (
            <EmptyState
              title={filtered ? "No tickets match your filters" : "No open tickets"}
              description={filtered ? "Try other filters." : "New customer requests will appear here."}
              action={filtered && <ButtonLink href="/tickets" variant="secondary">Clear filters</ButtonLink>}
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200 text-sm">
                <caption className="sr-only">Support tickets, page {p.page}</caption>
                <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-600">
                  <tr>
                    <th scope="col" className="px-5 py-3">Ticket</th>
                    <th scope="col" className="hidden px-5 py-3 md:table-cell">Account</th>
                    <th scope="col" className="px-5 py-3">Status</th>
                    <th scope="col" className="hidden px-5 py-3 sm:table-cell">Priority</th>
                    <th scope="col" className="hidden px-5 py-3 lg:table-cell">SLA</th>
                    <th scope="col" className="hidden px-5 py-3 lg:table-cell">Assignee</th>
                    <th scope="col" className="hidden px-5 py-3 xl:table-cell">Opened</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {data.items.map((t) => (
                    <tr key={t.id} className="hover:bg-slate-50">
                      <th scope="row" className="px-5 py-3 text-left font-medium">
                        <Link href={`/tickets/${t.id}`} className="text-brand-700 hover:underline">
                          <span className="font-mono text-xs text-slate-500">{ticketNumber(t.number)}</span>{" "}
                          {t.subject}
                          {t.category === "complaint" && <span className="ml-2"><CategoryBadge category="complaint" /></span>}
                        </Link>
                      </th>
                      <td className="hidden px-5 py-3 text-slate-700 md:table-cell">{accountName(t.account_id)}</td>
                      <td className="px-5 py-3"><TicketStatusBadge status={t.status} /></td>
                      <td className="hidden px-5 py-3 sm:table-cell"><PriorityBadge priority={t.priority} /></td>
                      <td className="hidden px-5 py-3 lg:table-cell"><SlaBadge state={t.sla_state} /></td>
                      <td className="hidden px-5 py-3 text-slate-700 lg:table-cell">{personName(t.assignee_user_id)}</td>
                      <td className="hidden whitespace-nowrap px-5 py-3 text-slate-700 xl:table-cell">{formatDate(t.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        {data.total > 0 && (
          <div className="border-t border-slate-200">
            <Pagination total={data.total} page={p.page} pageSize={PAGE_SIZE} hrefForPage={(page) => href(p, page)} />
          </div>
        )}
      </Card>
    </>
  ); // prettier-ignore
}
