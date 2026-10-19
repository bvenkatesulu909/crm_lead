"use client";

import { ActionDialog, DialogField } from "@/components/action-dialog";
import {
  CATEGORY_LABELS,
  PRIORITY_LABELS,
  ticketNumber,
} from "@/components/tickets";
import {
  TICKET_CATEGORIES,
  TICKET_PRIORITIES,
  type DirectoryUser,
  type TicketCategory,
  type TicketPriority,
  type TicketStatus,
} from "@/lib/api-types";
import { type DialogState, initialDialogState } from "@/lib/dialog-state";
import { STATUS_ACTIONS, nextStatuses } from "@/lib/ticket-rules";

type Bound = (state: DialogState, formData: FormData) => Promise<DialogState>;

/** Ticket buttons for support staff. Every change asks for confirmation first. */
export function TicketActionBar({
  ticket,
  supportStaff,
  actions,
}: {
  ticket: {
    number: number;
    status: TicketStatus;
    priority: TicketPriority;
    category: TicketCategory;
    version: number;
    assigneeId: string | null;
    assigneeName: string;
  };
  supportStaff: DirectoryUser[];
  actions: {
    assign: Bound;
    priority: Bound;
    status: Partial<Record<Exclude<TicketStatus, "new">, Bound>>;
  };
}) {
  if (ticket.status === "closed") return null;
  const label = ticketNumber(ticket.number);

  return (
    <div role="group" aria-label="Ticket actions" className="flex flex-wrap gap-2">
      <ActionDialog
        triggerLabel={ticket.assigneeId ? "Reassign" : "Assign"}
        title={`Assign ${label}`}
        description={<>Currently: <strong>{ticket.assigneeName}</strong>. The assignee is responsible for answering in time.</>}
        confirmLabel="Assign ticket"
        action={actions.assign}
        initialState={initialDialogState}
      >
        {(errors) => (
          <DialogField id="ticket-assignee" label="Support employee" error={errors.assignee_id}>
            {(props) => (
              <select name="assignee_id" defaultValue="" {...props}>
                <option value="" disabled>Choose…</option>
                {supportStaff.filter((u) => u.id !== ticket.assigneeId).map((u) => (
                  <option key={u.id} value={u.id}>{u.display_name}</option>
                ))}
              </select>
            )}
          </DialogField>
        )}
      </ActionDialog>

      <ActionDialog
        triggerLabel="Priority / category"
        title={`Priority and category of ${label}`}
        description="A new priority recalculates the response and resolution deadlines from when the ticket was opened."
        confirmLabel="Save"
        action={actions.priority}
        initialState={initialDialogState}
      >
        {(errors) => (
          <>
            <input type="hidden" name="version" value={ticket.version} />
            <DialogField id="ticket-new-priority" label="Priority" error={errors.priority}>
              {(props) => (
                <select name="priority" defaultValue={ticket.priority} {...props}>
                  {TICKET_PRIORITIES.map((p) => <option key={p} value={p}>{PRIORITY_LABELS[p]}</option>)}
                </select>
              )}
            </DialogField>
            <DialogField id="ticket-new-category" label="Category" error={errors.category}>
              {(props) => (
                <select name="category" defaultValue={ticket.category} {...props}>
                  {TICKET_CATEGORIES.map((c) => <option key={c} value={c}>{CATEGORY_LABELS[c]}</option>)}
                </select>
              )}
            </DialogField>
          </>
        )}
      </ActionDialog>

      {nextStatuses(ticket.status).map((target) => {
        const info = STATUS_ACTIONS[target];
        const action = actions.status[target];
        if (!action) return null;
        return (
          <ActionDialog
            key={target}
            triggerLabel={info.label(ticket.status)}
            triggerVariant={info.danger ? "danger" : target === "resolved" ? "primary" : "secondary"}
            title={`${info.label(ticket.status)} ${label}?`}
            description={info.confirm}
            confirmLabel={info.label(ticket.status)}
            confirmVariant={info.danger ? "danger" : "primary"}
            action={action}
            initialState={initialDialogState}
          >
            {(errors) => (
              <DialogField id={`ticket-reason-${target}`} label="Reason" optional error={errors.reason}>
                {(props) => <input name="reason" maxLength={500} {...props} />}
              </DialogField>
            )}
          </ActionDialog>
        );
      })}
    </div>
  ); // prettier-ignore
}
