# Orders module (Phase 12)

Customer orders, created by staff in the CRM, with a status the customer can follow in the
portal. It is also what the AI assistant will use to answer "where is my order?".

## Built before Phase 11 (products and quotes)

The plan says an accepted **quote** becomes an order. Quotes and the product catalogue
(Phase 11) don't exist yet because the owner moved orders forward for the assistant (ADR 0003).
So for now:

- Staff create orders **directly**, typing the lines (description, optional product code,
  quantity, unit price, tax rate).
- Every line is already a **snapshot**: amounts are stored on the line and never recalculated
  from a price list. When Phase 11 arrives, "convert accepted quote" will create the same
  kind of order with lines copied from the quote. That will need one new column (`quote_id`)
  and a new migration; nothing existing has to change.

## Concepts

| Thing | Meaning |
|---|---|
| Order | Belongs to one customer account. Number per organisation: `SO-0001`, `SO-0002`, … |
| Line | What is ordered: quantity × unit price, plus tax. The server calculates every amount |
| Customer reference | The customer's own purchase-order number. They see it |
| Internal note | Staff only. Never sent to the portal |
| History | Every status change: who, when and an optional staff-only note. Can't be edited or deleted |

## Status flow

```
draft ──► confirmed ──► in_fulfilment ──► shipped ──► delivered   (final)
  │           │               │
  └───────────┴───────────────┴──► cancelled                      (final)
```

- **Only drafts can be edited.** Confirming freezes the lines and the totals.
- A draft needs at least one line before it can be confirmed (409 `order_has_no_lines`).
- **Cancelling needs a reason, and the customer sees it.** Once shipped, an order can't be
  cancelled any more; that will be a return or credit note (Phase 13).
- **An order with an invoice can't be cancelled** (409 `order_invoiced`). "Invoice" means a
  draft or issued one. Discard the draft invoice first; an issued invoice is corrected with a
  credit note instead, and the order stays as it is. How this works without the orders module
  importing invoices: see "Invoice lock" below.
- Wrong moves give 409 `invalid_status_transition`. Every change sends the `version` it
  loaded, so if someone else changed the order in the meantime you get 409
  `version_conflict` instead of overwriting their change.

## Money

- Stored as `NUMERIC` and handled as `Decimal` in Python. It is sent as **strings** in JSON
  (`"214.16"`), so no float rounding can creep in.
- Per line: `subtotal = round(qty × price)`, `tax = round(subtotal × rate / 100)`, rounding
  **half up** to cents. Order totals are the sum of the rounded lines, so the printed lines
  always add up to the printed total.
- The database refuses inconsistent totals (`total = subtotal + tax_total`, and the same for
  each line).
- The order form shows a live **preview** using the same rules (in exact whole cents with
  BigInt, `frontend/src/lib/order-math.ts`). The server still calculates the real amounts.
  Clients can't send totals: the API rejects any unknown field with 422.

## Who can do what

| Role | Sees | Can do |
|---|---|---|
| Tenant Admin, Sales Manager | all orders of the organisation | create, edit drafts, confirm, cancel, **fulfilment** (in fulfilment / shipped / delivered) |
| Sales Agent | orders on accounts **they own** | create for own accounts, edit drafts, confirm, cancel (not once fulfilment has started) |
| Support Agent | all orders of the organisation | read only (to answer customers) |
| Customer | **confirmed** orders of **their granted accounts** | follow the status (portal) |
| Super Admin | nothing | — |

Customers never see drafts, internal notes, who created or changed the order, or the history
notes; the portal API returns different, smaller response models. An order of another
customer, another tenant, or a draft is a **404**. A role that can see an order but not change
it gets a 403 when trying to change it.

## For the AI assistant

`app.modules.orders.api.customer_orders(session, principal, account_id=None, q=None)` and
`customer_order(session, principal, order_id)` run **as the signed-in customer**: exactly
the portal rules (own granted accounts, no drafts, no internal data). Staff identities are
refused. `q` accepts an order number such as `SO-12`.

## API

Staff (`/api/v1/orders`): `GET` (filters `q` = number or customer reference, `status`,
`account_id`, `sort`, paging), `POST` (draft), `GET /{id}` (with lines and history),
`PUT /{id}` (replace a draft, with `version`), `POST /{id}/status`
(`status`, `version`, `reason` for cancel, `tracking_reference` for shipped,
`expected_delivery_date`, staff `note`).

Portal (`/api/v1/portal/orders`): `GET` (`account_id`, paging), `GET /{id}` (lines, totals,
tracking, timeline of status and time only).

Full contract: [api/openapi.json](api/openapi.json). Audit actions: `order.created`,
`order.updated`, `order.status_changed`.

## Screens

| Route | Who | What |
|---|---|---|
| `/orders` | staff | List with search (SO-number or reference), status filter, total, expected delivery |
| `/orders/new` (`?account=` preselects) | writers | Form with a line editor, live amount preview and an internal note. Saves a draft |
| `/orders/[id]` | staff | Lines and totals, details, history with notes, internal note (amber). Action bar shows only allowed steps: Edit draft, Confirm order, Start fulfilment, Mark as shipped (tracking), Mark as delivered, Cancel order (reason shown to the customer). Each asks for confirmation |
| `/orders/[id]/edit` | writers | Edit a draft (confirmed orders redirect back) |
| `/accounts/[id]` | staff | "Orders" card with the account's orders and a "New order" button |
| `/portal/orders`, `/portal/orders/[id]` | customers | Their orders. The detail page shows progress steps (Order received → Being prepared → On its way → Delivered), what was ordered, the tracking reference, the cancellation reason, and "Question about this order?" (opens a support ticket) |
| `/portal`, `/portal/accounts/[id]` | customers | Recent orders and orders per account |

## Invoice lock

`orders.invoiced_at` (migration `0007`) is set while the order has a live invoice. The
invoices module sets it with `orders.api.mark_invoiced` when it creates an invoice, and clears
it with `orders.api.release_invoiced` when the draft is discarded. Both are plain function calls
inside the same database transaction as the invoice itself, so the mark and the invoice are
saved or rolled back together. Orders never imports invoices, so the dependency only goes one
way (invoices → orders).

- `mark_invoiced` only marks an order of the caller's tenant that the caller may see and that
  is still in an invoiceable status. Its UPDATE locks the order row, the same lock a status
  change takes. So if "invoice it" and "cancel it" arrive at the same moment, whichever is
  second sees the first one's result: either the cancel gets `order_invoiced`, or the invoice
  gets `order_not_invoiceable`.
- The mark does not increase the order's `version`. It isn't an edit, so an order page that is
  already open keeps working.
- A check constraint (`ck_orders_not_cancelled_while_invoiced`) makes the database itself refuse
  a cancelled order that still has the mark.
- Migration 0007 marked the orders that already had a live invoice. Orders that were cancelled
  *before* this rule existed were left as they were.

## Database (migrations `0005`, `0007`)

- `orders` (`invoiced_at` added in 0007)
- `order_lines`
- `order_status_events`: append-only for the app role (UPDATE, DELETE and TRUNCATE are revoked)
- `order_number_counters`: atomic per-tenant numbering

All tenant-owned tables use composite foreign keys `(tenant_id, …)`, so an order can't point at
another tenant's account or user.

## Not done yet

- Quote → order conversion (Phase 11).
- Partial shipments and returns.
- E-mail notifications on status changes.
- Invoices from orders: done in Phase 13, see [invoices.md](invoices.md). The server blocks
  cancelling an invoiced order (see "Invoice lock").
- Cancelling an order whose issued invoice is fully credited isn't possible. Returns will
  handle that later. The lock is a narrow direct call, not a domain event. A general outbox can
  replace it later without changing the rule.
