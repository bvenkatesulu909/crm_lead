import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ReplyForm } from "@/components/ticket-forms";
import {
  CATEGORY_LABELS,
  CommentThread,
  Stars,
  TicketStatusBadge,
  ticketNumber,
} from "@/components/tickets";
import { Card, SuccessAlert } from "@/components/ui";
import { ApiError } from "@/lib/api-error";
import type { PortalComment, PortalTicket } from "@/lib/api-types";
import { formatDateTime } from "@/lib/format";
import { initialFormState } from "@/lib/form-state";
import { apiFetch } from "@/lib/server/api";

import { rateTicket, replyToTicket } from "../actions";
import { RatingForm } from "./rating-form";

export const metadata: Metadata = { title: "Ticket" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DONE: Record<string, string> = {
  created: "Your ticket was submitted. Our support team will get back to you.",
  replied: "Your reply was sent.",
  rated: "Thank you for your feedback!",
};

/** One of the customer's tickets. Another customer's ticket is a 404 from the API. */
export default async function PortalTicketPage({
  params,
  searchParams,
}: PageProps<"/portal/tickets/[id]">) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  if (!UUID.test(id)) notFound();
  let ticket: PortalTicket;
  let comments: PortalComment[];
  try {
    [ticket, comments] = await Promise.all([
      apiFetch<PortalTicket>(`/portal/tickets/${id}`),
      apiFetch<PortalComment[]>(`/portal/tickets/${id}/comments`),
    ]);
  } catch (error) {
    if (
      error instanceof ApiError &&
      (error.status === 404 || error.status === 403)
    )
      notFound();
    throw error;
  }
  const done = typeof query.done === "string" ? DONE[query.done] : undefined;

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link href="/portal/tickets" className="font-medium text-brand-700 hover:underline">← Support tickets</Link>
      </nav>
      {done && <div className="mb-4"><SuccessAlert>{done}</SuccessAlert></div>}
      <p className="font-mono text-sm text-slate-500">{ticketNumber(ticket.number)}</p>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{ticket.subject}</h1>
        <TicketStatusBadge status={ticket.status} portal />
      </div>
      <p className="mt-1 text-sm text-slate-600">
        {CATEGORY_LABELS[ticket.category]} · opened {formatDateTime(ticket.created_at)}
      </p>

      <Card className="mt-6">
        <div className="px-5 pt-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Your request</p>
          <p className="mt-1 whitespace-pre-line text-sm text-slate-800">{ticket.description}</p>
        </div>
        <CommentThread items={comments} emptyText="No replies yet. Our support team will answer soon." />
        {ticket.satisfaction_rating !== null ? (
          <p className="border-t border-slate-200 px-5 py-4 text-sm text-slate-700">
            Your rating: <Stars rating={ticket.satisfaction_rating} />
          </p>
        ) : (ticket.status === "resolved" || ticket.status === "closed") && (
          <RatingForm action={rateTicket.bind(null, ticket.id)} />
        )}
        {ticket.status === "closed" ? (
          <p className="border-t border-slate-200 px-5 py-4 text-sm text-slate-600">
            This ticket is closed. If you need more help, please{" "}
            <Link href="/portal/tickets/new" className="text-brand-700 hover:underline">open a new ticket</Link>.
          </p>
        ) : (
          <ReplyForm action={replyToTicket.bind(null, ticket.id)} initialState={initialFormState} />
        )}
      </Card>
    </>
  ); // prettier-ignore
}
