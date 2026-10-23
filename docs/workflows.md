# Workflow & Notifications (Phase 17, ADR 0006)

Step **17a** (done): domain events, notifications in the CRM and by e-mail, task reminder
e-mails. Step **17b** (done): automation rules defined by tenant admins.

## Automation rules (step 17b) - for tenant admins

**Automation** in the menu (admins only). A rule reads like a sentence:
*When* (trigger) … *and* (conditions, all must hold) … *then* (actions).

| Triggers (when…) | Record the rule looks at |
|---|---|
| A lead is assigned to someone | the lead |
| A quote needs approval / a customer accepts / declines a quote | the quote |
| A ticket is assigned / a customer replies on a ticket | the ticket |
| An order changes status | the order |
| *Schedule:* a sent quote expires within N days | the quote |
| *Schedule:* a task is overdue by N days | the task |

- **Conditions** test fields of that record: e.g. *largest line discount is more than 20*,
  *ticket priority is one of high, urgent*, *order total is at least 10000*. Comparisons: is,
  is not, is one of, more/less than, at least/at most. No code or formulas.
- **Actions:** *create a task* (for the record's owner or a named colleague; "{record}" in
  the subject becomes the record's name), *send a notification* (to the owner, a colleague,
  or everyone with a role), *change a field* - only **lead status** (never "converted") and
  **customer segment**.
- Rules act as the organisation's **Automation** identity: no login, fixed limited
  permissions, only inside the organisation. Everything goes through the owning module's
  rules and audit ("Automation" appears as the author; a lead's history says which rule).
- **Run log** (right side of the Automation page): every time a rule's conditions matched -
  *Done* (what it did), *Failed* (why; the rule's actions were all undone), or *Stopped*.
- **Safety limits:** a rule acts at most once per event (or once per record and due date for
  schedules); events caused by automation count as a deeper step and rules stop at depth 3
  (no endless loops); at most 500 automatic runs per organisation per hour
  (`CRM_WORKFLOW_ACTIONS_PER_HOUR`). Schedules are checked about once a minute by the worker.
- Notifications from rules only reach people who may see the record.

API (permission `workflow:manage`): `GET /workflows/catalogue`, `GET/POST /workflows/rules`,
`GET/PUT/DELETE /workflows/rules/{id}`, `GET /workflows/runs?rule_id=&limit=`.

## Notifications - what people get

| Notification | Who gets it | E-mail by default |
|---|---|---|
| Reminder for a task (its reminder time has come) | the person the task is for | yes |
| A task was assigned to you | the new assignee (not when you plan your own task) | no |
| A lead was assigned to you | the new owner | no |
| A quote is waiting for your approval | everyone who may approve - not the quote's owner/creator (four-eyes), unless tenant admin | yes |
| Your quote was approved / returned to draft | the quote's owner and creator | no |
| A customer accepted / declined your quote | the quote's owner and creator | accepted: yes |
| A ticket was assigned to you | the new assignee | no |
| A customer replied on your ticket | the ticket's assignee | no |

- The person who caused something is never notified about it.
- Nobody is ever told about a record they may not see: before writing a notification, the
  module that owns the record is asked whether this person may see it.
- Inactive people and people of other organisations are never notified.
- **In the CRM:** the inbox icon in the header shows the unread count; *Notifications* lists
  them, opening one marks it read and goes to the record; *Mark all as read*.
- **By e-mail:** *Notifications → E-mail settings* - tick which types also come by e-mail.
  E-mails are sent by the worker (locally they land in Mailpit, http://localhost:8025).
- The tasks bell (overdue / due soon) stays as it was.

## How it works (for developers)

1. A module calls `publish(session, tenant_id, "<event>", {ids…})` (`app/core/events.py`) in
   the **same transaction** as its change. It becomes an outbox job `event.<name>`.
2. The worker (`python -m app.worker`) hands every event to its subscribers. The notifications
   module's subscriber decides who should hear about it and writes one row per person
   (`notifications`), at most once per person and event - so a retried event never notifies
   twice.
3. If the person wants e-mails for that type, a `notification.email` job sends one.
4. The worker's **scheduler** runs before each round: open tasks whose `reminder_at` has passed
   get an `activity.reminder_due` event, once (`activities.reminder_sent_at`; changing the
   reminder time arms it again). Migration 0018 marks reminders that were already in the past
   as sent, so starting the worker doesn't send old reminders.

### Event catalogue

| Event | Published by | Data (IDs and codes only) |
|---|---|---|
| `lead.assigned` | leads (assign) | `lead_id`, `assignee_id`, `actor_id` |
| `activity.assigned` | activities (create/reassign open work for someone else) | `activity_id`, `assignee_id`, `actor_id` |
| `activity.reminder_due` | worker scheduler | `activity_id`, `assignee_id` |
| `quote.approval_requested` | quotes (submit, discount above the limit) | `quote_id`, `actor_id` |
| `quote.approved` / `quote.rejected` | quotes (approve / return to draft) | `quote_id`, `actor_id` |
| `quote.accepted` / `quote.declined` | quotes (customer or staff record the answer) | `quote_id`, `actor_id` |
| `ticket.assigned` | support (assign) | `ticket_id`, `assignee_id`, `actor_id` |
| `ticket.customer_replied` | support (customer comment) | `ticket_id` |
| `order.status_changed` | orders | `order_id`, `status`, `previous`, `actor_id` (no subscriber yet - for rules in 17b) |
| `contract.activated` / `contract.terminated` | contracts (a manager activates or ends a contract) | `contract_id`, `actor_id` |
| `contract.renewal_due` | contracts (the daily worker, once the renewal date is reached) | `contract_id` (added in step C3) |
| `contract.expired` | contracts (the daily worker, when the end date has passed) | `contract_id` (added in step C3) |

Rules: names must be in `EVENT_NAMES`; no personal data in payloads; subscribers must be safe
to run twice; events caused by automation carry a `depth` (rules stop at 3, step 17b).

## API (all under `/api/v1`, permission `notification:read`, staff only)

| Method and path | What it does |
|---|---|
| `GET /notifications?unread_only=&limit=` | my notifications, newest first, plus the unread count |
| `POST /notifications/{id}/read` | mark one as read (someone else's: 404) |
| `POST /notifications/read-all` | mark all as read |
| `GET /notifications/preferences`, `PUT /notifications/preferences` | which types also come by e-mail |

## Not built yet

- Notifications for customers in the portal; webhooks (Phase 19).
- More triggers (e.g. "account without activity for N days") and more fields to change.
