# Invoices and payments (Phase 13)

Invoices are created from confirmed orders. Payments are entered by hand, and credit notes
correct invoices. Customers see what they owe in the portal. The AI assistant will use the
same rules to answer "what do I still owe?" or "did you receive my payment?".

## The life of an invoice

```
order (confirmed or later) ──Create invoice──► DRAFT (no number, customer can't see it)
                                                 │                 │
                                              Issue              Discard
                                                 ▼                 ▼
                                   ISSUED INV-0001 (frozen)     DISCARDED (never numbered;
                                     │        │                  the order can be invoiced again)
                         record payments   credit notes CN-0001
                                     ▼        ▼
                     amount due = total − payments − credit notes
```

- **Lines are copied from the order** (a snapshot). The customer account, currency and amounts
  come from the order too, never from the browser.
- **One live invoice per order.** The database enforces this with a partial unique index.
- **An invoiced order can't be cancelled.** Creating the invoice marks the order through
  `orders.api.mark_invoiced`, and discarding the draft clears the mark again
  (`orders.api.release_invoiced`). Both happen in the same transaction as the invoice. See
  "Invoice lock" in [orders.md](orders.md).
- **Numbers are given at issue time and have no gaps.** The counter row is taken inside the
  issuing transaction. If issuing fails, the number is given back. Discarded drafts never had
  one. Invoices (`INV-`) and credit notes (`CN-`) have separate counters per organisation.
- **An issued invoice is frozen by the database.** A trigger (`invoices_freeze_issued`,
  migration 0006) refuses any change to its number, lines, amounts, dates, account or status.
  Only the running balance may change (`amount_paid`, `amount_credited`, `balance_due`).
  Invoices can't be deleted. Corrections are made with a credit note, never by editing.

## Payments

- Entered manually: amount, date received (not in the future), method (bank transfer, card,
  cash, other) and an optional reference. No payment provider and no card data.
- A payment can't be more than the amount still owed (no overpayments yet).
- **Payments can't be edited or deleted.** A wrong entry or bounced transfer is undone with
  **Reverse**. This adds a reversal row with a reason, and the amount is owed again. A payment
  can be reversed only once, and a reversal can't be reversed. The customer sees only the
  payments that count; reversed payments and reasons stay internal.

## Credit notes

- They reduce what the customer owes, with a reason the **customer sees**.
- A credit note can't be more than the amount still owed, so the balance never goes negative.
  To refund money that was already paid, reverse the payment first and refund it outside the
  CRM. Proper refunds come with the payment-provider integration.
- Credit notes are insert-only, like their lines.

## Payment state (calculated when read, never stored)

| State | Meaning | Customer sees |
|---|---|---|
| draft / discarded | not a real invoice (yet) | — (never shown) |
| open | issued, nothing received, not due yet | Awaiting payment |
| partially_paid | something paid or credited, rest not due yet | Partly paid |
| overdue | money owed after the due date | Payment overdue |
| paid | nothing owed, money received | Paid |
| credited | nothing owed, settled entirely by credit notes | Credited |

The due date defaults to 14 days after issuing. It can be at most 365 days later and is set
when issuing.

## Who can do what

| Role | Sees | Can do |
|---|---|---|
| Tenant Admin, Sales Manager | all invoices of the organisation | create from order, issue, discard drafts, credit notes (`invoice:manage`); record and reverse payments (`payment:record`) |
| Support Agent | all invoices | read only (to answer customers) |
| Sales Agent | invoices on accounts **they own** | read only |
| Customer | **issued** invoices of **their granted accounts** | read: lines, credit notes, counted payments, amount due |
| Super Admin | nothing | — |

Another customer's invoice, another tenant's invoice, or a draft is a **404**. Someone who can
see an invoice but not change it gets **403** for a change. A payment ID from another invoice
gives a 404 (ID tampering).

## For the AI assistant

`app.modules.invoices.api.customer_invoices(session, principal, account_id=…, order_id=…,
state="unpaid"|"overdue"|"paid", q="INV-12")` and `customer_invoice(session, principal,
invoice_id)` run **as the signed-in customer**, with exactly the portal rules. Staff identities
are refused.

## API

Staff (`/api/v1/invoices`):
- `GET` with filters `q` (number or customer reference), `state` (`draft`, `unpaid`,
  `overdue`, `paid`, `discarded`), `account_id`, `order_id`, `sort` and paging.
- `POST` `{order_id}` creates a draft.
- `GET /{id}` returns lines, credit notes and payments.
- `POST /{id}/issue` `{version, due_date?}`.
- `POST /{id}/discard` `{version}`.
- `POST /{id}/payments` `{amount, received_on, method, reference?}`.
- `POST /{id}/payments/{payment_id}/reverse` `{reason}`.
- `POST /{id}/credit-notes` `{reason, lines[]}`.

Portal (`/api/v1/portal/invoices`): `GET` (`account_id`, `order_id`, `state`, paging) and
`GET /{id}`.

Error codes:
- `order_not_invoiceable`, `order_already_invoiced`
- on the orders API: `order_invoiced` (cancelling an order that has a draft or issued invoice)
- `invoice_not_draft`, `invoice_not_issued`
- `invalid_amount`
- `payment_not_reversible`, `payment_not_found`
- `version_conflict`

Audit actions: `invoice.created`, `invoice.issued`, `invoice.discarded`, `payment.recorded`,
`payment.reversed`, `credit_note.issued`. Full contract: [api/openapi.json](api/openapi.json).

## Screens

| Route | Who | What |
|---|---|---|
| `/invoices` | staff | List with search, filter (unpaid, overdue, paid, drafts, discarded), amount due, due date |
| `/invoices/[id]` | staff | Lines, Balance (total − credit notes − payments = amount due), payments (reversed ones struck through, with the reversal and its reason), credit notes, details. Buttons depend on role and state: Issue invoice (due date), Discard draft, Record payment (pre-filled with the amount owed), Issue credit note, Reverse (per payment). Each asks for confirmation |
| `/orders/[id]` | staff | "Invoice" card: link and state, or **Create invoice**. Cancelling an invoiced order warns that a credit note is needed |
| `/accounts/[id]` | staff | "Unpaid invoices" card |
| `/portal/invoices`, `/portal/invoices/[id]` | customers | Total currently owed; each invoice with a due/overdue note, lines, credit notes with reasons, payments received, balance, and "Question about this invoice?" (opens a ticket) |
| `/portal`, `/portal/accounts/[id]`, `/portal/orders/[id]` | customers | "Invoices to pay", invoices per account, and a link from the order to its invoice |

## Database (migration `0006`)

- `invoices`: trigger, plus DELETE revoked.
- `invoice_lines`, `credit_notes`, `credit_note_lines`, `payments`: insert-only for the app role.
- `billing_number_counters`: per tenant and series.

Every table uses composite `(tenant_id, …)` foreign keys. Check constraints keep totals and the
balance consistent: `balance_due = total − amount_paid − amount_credited`, and it is never
negative.

## Known limits / later

- **Cancelling an invoiced order** is refused by the server (409 `order_invoiced`, migration
  0007). If the invoice is still a draft, discard it first. An issued invoice is final: the
  money side is corrected with a credit note and the order stays as it is. Cancelling or
  returning an order whose invoice was fully credited comes with returns. The lock is a narrow
  direct call (`orders.api`), not a domain event. An outbox can take its place later.
- Invoice PDFs and e-mailing (with the documents phase), overpayments and refunds, partial
  invoicing of an order, payment reminders, payment providers.
