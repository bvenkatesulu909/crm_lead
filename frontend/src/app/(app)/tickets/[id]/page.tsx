import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ReplyForm } from "@/components/ticket-forms";
import {
  ChannelBadge,
  CommentThread,
  CategoryBadge,
  PriorityBadge,
  SlaBadge,
  Stars,
  TicketStatusBadge,
  ticketNumber,
} from "@/components/tickets";
import { Card, Forbidden, SuccessAlert } from "@/components/ui";
import { ApiError } from "@/lib/api-error";
import type {
  Account,
  DirectoryUser,
  Ticket,
  TicketComment,
} from "@/lib/api-types";
import { formatDateTime } from "@/lib/format";
import { initialFormState } from "@/lib/form-state";
import { canManageTickets, canReadAccounts } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";
import { nextStatuses } from "@/lib/ticket-rules";

import {
  addStaffComment,
  assignTicket,
  changePriority,
  changeTicketStatus,
} from "../actions";
import { TicketActionBar } from "./ticket-action-bar";

export const metadata: Metadata = { title: "Ticket" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const DONE: Record<string, string> = {
  created: "The ticket was created.",
  replied: "Your reply was sent to the customer.",
  noted: "The internal note was added.",
  status: "The status was changed.",
  assigned: "The ticket was assigned.",
  priority: "The priority was changed.",
};

async function loadTicket(id: string): Promise<Ticket | "forbidden"> {
  if (!UUID.test(id)) notFound();
  try {
    return await apiFetch<Ticket>(`/tickets/${id}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    if (error instanceof ApiError && error.status === 403) return "forbidden";
    throw error;
  }
}

export default async function TicketPage({
  params,
  searchParams,
}: PageProps<"/tickets/[id]">) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  const [ticket, me] = await Promise.all([loadTicket(id), getMe()]);
  if (ticket === "forbidden") return <Forbidden />;

  const [comments, people, account] = await Promise.all([
    apiFetch<TicketComment[]>(`/tickets/${id}/comments`),
    apiFetch<DirectoryUser[]>("/users"),
    canReadAccounts(me)
      ? apiFetch<Account>(`/accounts/${ticket.account_id}`).catch(() => null)
      : Promise.resolve(null),
  ]);
  const nameOf = (userId: string | null, none = "Unassigned") =>
    userId
      ? (people.find((p) => p.id === userId)?.display_name ?? "Customer")
      : none;
  const manage = canManageTickets(me);
  const done = typeof query.done === "string" ? DONE[query.done] : undefined;

  const facts: [string, React.ReactNode][] = [
    [
      "Account",
      account ? (
        <Link
          href={`/accounts/${account.id}`}
          className="text-brand-700 hover:underline"
        >
          {account.name}
        </Link>
      ) : (
        "Customer account"
      ),
    ],
    [
      "Requested by",
      ticket.requester_user_id
        ? nameOf(ticket.requester_user_id)
        : "Created by staff",
    ],
    ["Assignee", nameOf(ticket.assignee_user_id)],
    ["Opened", formatDateTime(ticket.created_at)],
    [
      "First response due",
      ticket.first_responded_at
        ? `Answered ${formatDateTime(ticket.first_responded_at)}`
        : formatDateTime(ticket.first_response_due_at),
    ],
    [
      "Resolution due",
      ticket.resolved_at
        ? `Resolved ${formatDateTime(ticket.resolved_at)}`
        : formatDateTime(ticket.resolution_due_at),
    ],
  ];

  const statusActions = Object.fromEntries(
    nextStatuses(ticket.status).map((target) => [
      target,
      changeTicketStatus.bind(null, ticket.id, target),
    ]),
  );

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link href="/tickets" className="font-medium text-brand-700 hover:underline">← Support</Link>
      </nav>
      {done && <div className="mb-4"><SuccessAlert>{done}</SuccessAlert></div>}

      <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="font-mono text-sm text-slate-500">{ticketNumber(ticket.number)}</p>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{ticket.subject}</h1>
          <div className="mt-2 flex flex-wrap gap-2">
            <TicketStatusBadge status={ticket.status} />
            <PriorityBadge priority={ticket.priority} />
            <CategoryBadge category={ticket.category} />
            <SlaBadge state={ticket.sla_state} />
            <ChannelBadge channel={ticket.channel} />
          </div>
          {ticket.satisfaction_rating !== null && (
            <p className="mt-2 text-sm text-slate-700">
              Customer satisfaction: <Stars rating={ticket.satisfaction_rating} />
              {ticket.satisfaction_comment && <span className="ml-2 italic text-slate-600">“{ticket.satisfaction_comment}”</span>}
            </p>
          )}
        </div>
        {manage && (
          <TicketActionBar
            key={ticket.version}
            ticket={{ number: ticket.number, status: ticket.status, priority: ticket.priority, category: ticket.category, version: ticket.version, assigneeId: ticket.assignee_user_id, assigneeName: nameOf(ticket.assignee_user_id) }}
            supportStaff={people.filter((p) => p.support)}
            actions={{ assign: assignTicket.bind(null, ticket.id), priority: changePriority.bind(null, ticket.id), status: statusActions }}
          />
        )}
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">Conversation</h2>
          <div className="px-5 pt-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Original request</p>
            <p className="mt-1 whitespace-pre-line text-sm text-slate-800">{ticket.description}</p>
          </div>
          <CommentThread items={comments} emptyText="No replies yet." />
          {manage && ticket.status !== "closed" && (
            <ReplyForm key={ticket.version} action={addStaffComment.bind(null, ticket.id)} initialState={initialFormState} staff />
          )}
          {ticket.status === "closed" && (
            <p className="border-t border-slate-200 px-5 py-4 text-sm text-slate-600">This ticket is closed.</p>
          )}
        </Card>
        <Card>
          <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">Details</h2>
          <dl className="space-y-3 px-5 py-4 text-sm">
            {facts.map(([label, value]) => (
              <div key={label}>
                <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</dt>
                <dd className="mt-0.5 text-slate-900">{value}</dd>
              </div>
            ))}
          </dl>
        </Card>
      </div>
    </>
  ); // prettier-ignore
}
