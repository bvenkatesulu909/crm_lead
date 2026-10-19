import type { TicketStatus } from "@/lib/api-types";

/**
 * Which status buttons to SHOW for a ticket. Copy of backend/app/modules/support/rules.py for
 * display only; the API enforces the real rules and its error is shown if they ever differ.
 */
export const TICKET_TRANSITIONS: Record<TicketStatus, TicketStatus[]> = {
  new: ["open", "pending_customer", "resolved", "closed"],
  open: ["pending_customer", "resolved", "closed"],
  pending_customer: ["open", "resolved", "closed"],
  resolved: ["open", "closed"],
  closed: [],
};

/** Button wording per target status (from the support agent's point of view). */
export const STATUS_ACTIONS: Record<
  Exclude<TicketStatus, "new">,
  { label: (from: TicketStatus) => string; confirm: string; danger?: boolean }
> = {
  open: {
    label: (from) => (from === "new" ? "Start work" : "Reopen"),
    confirm: "The ticket moves back to the support team's active work.",
  },
  pending_customer: {
    label: () => "Wait for customer",
    confirm:
      "Use this after asking the customer something. Their reply reopens the ticket.",
  },
  resolved: {
    label: () => "Resolve",
    confirm: "The customer can still reply; that reopens the ticket.",
  },
  closed: {
    label: () => "Close",
    confirm:
      "A closed ticket is final: nobody can change it or reply any more.",
    danger: true,
  },
};

export function nextStatuses(
  status: TicketStatus,
): Exclude<TicketStatus, "new">[] {
  return TICKET_TRANSITIONS[status].filter(
    (s): s is Exclude<TicketStatus, "new"> => s !== "new",
  );
}
