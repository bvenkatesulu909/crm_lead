import { cx } from "@/components/ui";
import type {
  SlaState,
  TicketPriority,
  TicketStatus,
  TicketCategory,
} from "@/lib/api-types";
import { formatDateTime } from "@/lib/format";

/** Shared ticket UI: badges and the conversation thread (staff and portal). */

export const ticketNumber = (n: number) => `T-${String(n).padStart(4, "0")}`;

export const TICKET_STATUS_LABELS: Record<TicketStatus, string> = {
  new: "New",
  open: "In progress",
  pending_customer: "Waiting for customer",
  resolved: "Resolved",
  closed: "Closed",
};

/** What customers read: "Waiting for customer" becomes "Waiting for your reply". */
export const PORTAL_STATUS_LABELS: Record<TicketStatus, string> = {
  ...TICKET_STATUS_LABELS,
  open: "We're working on it",
  pending_customer: "Waiting for your reply",
};

export const CATEGORY_LABELS: Record<TicketCategory, string> = {
  question: "Question",
  problem: "Problem",
  request: "Request",
  complaint: "Complaint",
  feedback: "Feedback",
};

export function CategoryBadge({ category }: { category: TicketCategory }) {
  return (
    <span
      className={
        category === "complaint"
          ? "rounded-full bg-red-50 px-2.5 py-0.5 text-xs font-medium text-red-700 ring-1 ring-inset ring-red-200"
          : "rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-700"
      }
    >
      {CATEGORY_LABELS[category]}
    </span>
  );
}

/** "★★★★☆ 4/5" - the customer's satisfaction rating. */
export function Stars({ rating }: { rating: number }) {
  return (
    <span
      aria-label={`${rating} of 5`}
      className="whitespace-nowrap text-amber-500"
    >
      {"★".repeat(rating)}
      <span className="text-slate-300">{"★".repeat(5 - rating)}</span>
      <span className="ml-1 text-xs text-slate-600">{rating}/5</span>
    </span>
  );
}

export const PRIORITY_LABELS: Record<TicketPriority, string> = {
  low: "Low",
  normal: "Normal",
  high: "High",
  urgent: "Urgent",
};

const pill =
  "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset";

const statusStyle: Record<TicketStatus, string> = {
  new: "bg-sky-50 text-sky-800 ring-sky-200",
  open: "bg-amber-50 text-amber-800 ring-amber-200",
  pending_customer: "bg-violet-50 text-violet-800 ring-violet-200",
  resolved: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  closed: "bg-slate-100 text-slate-700 ring-slate-300",
};

export function TicketStatusBadge({
  status,
  portal = false,
}: {
  status: TicketStatus;
  portal?: boolean;
}) {
  return (
    <span className={cx(pill, statusStyle[status])}>
      {(portal ? PORTAL_STATUS_LABELS : TICKET_STATUS_LABELS)[status]}
    </span>
  );
}

const priorityStyle: Record<TicketPriority, string> = {
  low: "bg-slate-50 text-slate-600 ring-slate-200",
  normal: "bg-slate-100 text-slate-700 ring-slate-300",
  high: "bg-orange-50 text-orange-800 ring-orange-200",
  urgent: "bg-red-50 text-red-800 ring-red-200",
};

export function PriorityBadge({ priority }: { priority: TicketPriority }) {
  return (
    <span className={cx(pill, priorityStyle[priority])}>
      {PRIORITY_LABELS[priority]}
    </span>
  );
}

const slaText: Record<SlaState, string> = {
  on_track: "SLA on track",
  at_risk: "SLA at risk",
  breached: "SLA breached",
  met: "SLA met",
};
const slaStyle: Record<SlaState, string> = {
  on_track: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  at_risk: "bg-amber-50 text-amber-900 ring-amber-300",
  breached: "bg-red-600 text-white ring-red-600",
  met: "bg-emerald-50 text-emerald-800 ring-emerald-200",
};

export function SlaBadge({ state }: { state: SlaState }) {
  return <span className={cx(pill, slaStyle[state])}>{slaText[state]}</span>;
}

export function ChannelBadge({
  channel,
}: {
  channel: "portal" | "staff" | "assistant";
}) {
  if (channel !== "assistant") return null;
  return (
    <span className={cx(pill, "bg-brand-50 text-brand-800 ring-brand-100")}>
      Handed over by assistant
    </span>
  );
}

type ThreadItem = {
  id: string;
  body: string;
  author_name: string;
  author_type: "staff" | "customer" | "system";
  created_at: string;
  visibility?: "public" | "internal";
};

/** The conversation. Internal notes (staff view only) are clearly marked. */
export function CommentThread({
  items,
  emptyText,
}: {
  items: ThreadItem[];
  emptyText: string;
}) {
  if (items.length === 0)
    return <p className="px-5 py-6 text-sm text-slate-600">{emptyText}</p>;
  return (
    <ol className="space-y-3 px-5 py-4">
      {items.map((c) => {
        const internal = c.visibility === "internal";
        return (
          <li
            key={c.id}
            className={cx(
              "rounded-lg p-4 text-sm ring-1",
              internal
                ? "bg-amber-50 ring-amber-200"
                : c.author_type === "customer"
                  ? "bg-white ring-slate-200"
                  : "bg-brand-50/60 ring-brand-100",
            )}
          >
            <p className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
              <span className="font-semibold text-slate-900">
                {c.author_name}
              </span>
              {internal && (
                <span className="rounded bg-amber-200 px-1.5 py-0.5 font-semibold text-amber-900">
                  Internal note — not visible to the customer
                </span>
              )}
              <time dateTime={c.created_at}>
                {formatDateTime(c.created_at)}
              </time>
            </p>
            <p className="mt-2 whitespace-pre-line text-slate-800">{c.body}</p>
          </li>
        );
      })}
    </ol>
  );
}
