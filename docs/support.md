# Customer Support module (Phase 14)

Support tickets between customers (portal) and the support team (staff CRM), with SLA
tracking, internal notes and the **human handoff** the AI assistant will use.

## Concepts

| Thing | Meaning |
|---|---|
| Ticket | A customer's request about one of their accounts. Number per organisation: `T-0001`, `T-0002`, … |
| Status | `new` → `open` (In progress) ↔ `pending_customer` (Waiting for customer) → `resolved` → `closed` (final). Resolved can reopen. |
| Priority | low / normal / high / urgent — sets the SLA deadlines |
| Channel | where it came from: `portal` (customer), `staff` (e.g. phone call), `assistant` (AI handoff) |
| Comment | `public` = the customer sees it; `internal` = staff-only note. Comments can't be edited or deleted. |

**Automatic rules**
- The first *public* staff reply records the first-response time and moves a `new` ticket to `open`.
- A customer reply on a `pending_customer` or `resolved` ticket moves it back to `open`.
- Closed tickets can't be changed or answered (409 `ticket_closed`).
- Changing the priority recalculates the deadlines from when the ticket was opened.

## SLA (service-level agreement)

| Priority | First response | Resolution |
|---|---|---|
| Urgent | 1 hour | 8 hours |
| High | 4 hours | 24 hours |
| Normal | 8 hours | 3 days |
| Low | 24 hours | 5 days |

State, calculated on every read: **on track**, **at risk** (less than 25 % of the time left before
the next deadline), **breached**, or **met** (resolved in time). Staff can filter "SLA overdue".
Targets are code constants for now (`backend/app/modules/support/rules.py`); per-organisation SLA
settings and business hours can come later. No background job is needed.

## Who can do what

| Role | Sees | Can change |
|---|---|---|
| Support Agent, Tenant Admin | all tickets of the organisation | reply, internal notes, assign, status, priority, create for a customer |
| Sales Manager | all tickets of the organisation | — (read-only) |
| Sales Agent | tickets on accounts **they own** | — (read-only) |
| Customer | tickets on **their granted accounts** only | open tickets, reply (public only) |
| Super Admin | nothing | — |

Customers never receive assignees, SLA data, channels, requester IDs or internal notes — the
portal endpoints return different, smaller response models. Another customer's or another
tenant's ticket is a 404. Assignees must be active support staff of the same organisation.

## Human handoff (for the AI assistant)

`app.modules.support.api.create_customer_ticket(session, principal, account_id=…, subject=…,
description=…, channel="assistant")`

- Runs **as the signed-in customer**: only accepts that customer's granted accounts (404
  otherwise) and refuses staff identities.
- Creates a normal ticket marked "Handed over by assistant" for support staff; the customer
  sees it in their portal like any other ticket.
- The assistant phase will put a short conversation summary in the description and tell the
  customer the ticket number.

## API

Staff (`/api/v1/tickets`): `GET` (filters: `q` subject or `T-12`, `status`, `priority`,
`assignee_id`, `unassigned`, `account_id`, `overdue`, `sort`, paging), `POST`, `GET /{id}`,
`PATCH /{id}` (priority + version), `POST /{id}/status`, `POST /{id}/assign`,
`GET|POST /{id}/comments`.

Portal (`/api/v1/portal/tickets`): `GET`, `POST`, `GET /{id}`, `GET|POST /{id}/comments`.

Full contract: [api/openapi.json](api/openapi.json). Audit actions: `ticket.created`,
`ticket.assigned`, `ticket.status_changed`, `ticket.priority_changed`.

## Screens

| Route | Who | What |
|---|---|---|
| `/tickets` | staff | List with search, status (default: open tickets), priority, "assigned to me / unassigned / SLA overdue", SLA badge, assignee |
| `/tickets/new` | support | Create a ticket for a customer account (e.g. after a phone call) |
| `/tickets/[id]` | staff | Conversation incl. internal notes (amber, labelled), details with deadlines, action bar: Assign, Priority, Start work / Wait for customer / Resolve / Reopen / Close — each with a confirmation dialog (Close warns it is final). Reply form says explicitly "Send reply to customer" or "Add internal note" |
| `/portal/tickets`, `/portal/tickets/new`, `/portal/tickets/[id]` | customers | Their tickets, open a ticket (own accounts only), conversation with public replies |
| `/portal`, `/portal/accounts/[id]` | customers | Recent tickets and per-account tickets |

## Database (migration `0004`)

`tickets`, `ticket_comments` (append-only for the app role), `ticket_number_counters`
(atomic per-tenant numbering with `INSERT … ON CONFLICT DO UPDATE … RETURNING`).

## Not done yet

Knowledge-base articles (planned with the assistant's RAG), attachments, e-mail notifications,
per-organisation SLA settings and business hours.
