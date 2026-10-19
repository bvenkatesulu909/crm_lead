# Products, price books and quotes (Phase 11 / gap-analysis Phase E1)

This module covers what you sell (the **catalogue**), what it costs (**price books**) and the
offers you send to customers (**quotes**). An accepted quote becomes a draft **order**, which
completes the original Phase 12 requirement.

## Concepts

| Thing | Meaning |
|---|---|
| Product | Something you sell: product, service or subscription. Code (SKU) unique per organisation, unit (each, hour, month), tax rate. Inactive products can't be quoted |
| Price book | A list of selling prices in **one currency** (e.g. "Standard EUR"). One book per currency can be the default |
| Price | The unit price (without tax) of one product in one price book |
| Quote | An offer to one customer account, numbered per organisation: `QT-0007`. Optionally linked to a deal (opportunity) and a contact |
| Quote line | Product, quantity and discount %. **The price is never typed in**: the server takes it from the price book |
| Revision | A changed version of a sent quote: same number, `QT-0007 rev 2`. The old version is kept as *superseded* |
| History | Every step (created, submitted, approved, sent, accepted…), who and when. Insert-only |

## Who can do what

| Role | Catalogue | Quotes |
|---|---|---|
| Tenant admin, sales manager | read + change products, price books, prices | all quotes; **approve** discounts |
| Sales agent | read | own quotes and quotes for own customers |
| Support agent | read | — |
| Customer (portal) | — | sees **sent / accepted / declined** quotes of their own accounts; can accept or decline |

As everywhere: the buttons in the UI are for display only, the API checks every rule again.
A quote someone may not see answers **404**, never 403, so its existence is not revealed.

## How prices are calculated

1. The list price comes from the quote's price book (`list_price`).
2. The discount is applied **to the unit price** and rounded to cents:
   `net unit price = round(list price × (100 − discount) / 100)`.
3. The line amount is `quantity × net unit price`, tax is calculated from the product's tax
   rate - exactly like an order line.

Because of step 2, an order created from the quote has **the same totals to the cent**. The
quote form shows a live preview with the same rules (`previewTotals` in `src/lib/quotes.ts`);
a unit test checks it against values produced by the server code.

## Status flow and approval

```
draft ──submit──► approved ──send──► sent ──► accepted ──► (order created)
  ▲      │                             │
  │      └─► pending_approval ─approve─┘ ──► declined
  └──reject (with reason)──┘
any of pending_approval / approved / sent / declined ──revise──► new draft revision (old one: superseded)
```

- **Approval:** a quote needs a manager's approval when any line discount is above the
  organisation's **approval limit** (10 % unless changed). Without such a discount, submitting
  approves it straight away.
- **Approval limit (step E2c):** tenant admins change it on **Quotes → Settings**
  (`/quotes/settings`; API `GET`/`PUT /api/v1/quotes/settings`, permission
  `quote:settings:manage`). 0 = every discount needs approval, 100 = never. Everyone who works
  with quotes can read it, and the quote form's preview uses it. It applies when a quote is
  submitted; quotes already waiting keep waiting. Each organisation has its own limit; changes
  are audited and protected against two admins overwriting each other (409
  `version_conflict`).
- **Four-eyes rule:** a manager can't approve a quote they own or created - another manager
  must (tenant admins are the exception).
- **Only drafts can be edited.** Submitting re-prices the lines from the current price book.
- **Validity:** a quote is valid until its `valid_until` date (default 30 days). An expired
  sent quote can't be accepted (409 `quote_expired`); revise it instead.
- **Customer answer:** the customer accepts or declines in the portal, or staff record the
  answer (e.g. a signed PDF arrived by e-mail). Declining needs a reason.
- **To order:** an accepted quote becomes a **draft order** with the same lines and prices,
  once (`quote.order_id`). The order then follows the normal order flow (docs/orders.md).

## Printing / PDF

- **Stored PDF (step E2a, ADR 0005).** When a quote is **sent**, a background job
  (`quote.pdf`) draws the PDF with ReportLab and stores it in the file store (SeaweedFS) as a
  *document* of the quote. That file is what the customer received; it never changes. A
  revision gets its own PDF (`QT-0007-rev2.pdf`).
- **Download PDF** on the quote page (staff) and in the portal (customers). The browser asks
  the Next.js server (`/quotes/<id>/pdf`, `/portal/quotes/<id>/pdf`), which fetches the file
  from the API with the user's token - the token never reaches the browser. The API applies
  the normal rules: people who may not see the quote get 404; a quote that wasn't sent yet
  gives 409 `quote_not_sent`; without a file store 503. If the worker hasn't run yet, the PDF
  is made on the first download.
- The file's SHA-256 checksum is saved; a damaged file is refused (500 `document_integrity`).
- The PDF never contains internal notes, approval details or the status.
- `/print/quotes/<id>` still shows a printable page (browser **Print → Save as PDF**).

## Sending by e-mail (step E2b, ADR 0005)

- **Send by e-mail** on an approved quote (or **E-mail again** on a sent one). The e-mail
  goes to the quote's **contact** - the API looks up the address; the browser can't choose a
  recipient. A contact with an e-mail address is required (409 `quote_no_recipient`).
- An approved quote becomes **sent** at once; a `quote.email` job is saved in the same
  transaction. The worker (`python -m app.worker`) then sends the e-mail with the stored PDF
  attached, a link to the customer portal, an optional personal message, and **Reply-To**
  the quote's owner. Locally every e-mail lands in Mailpit (http://localhost:8025).
- The quote shows the e-mail status: *On its way…*, *Sent to the contact*, or *Could not be
  sent*. The history notes "E-mail sent to …" or "E-mail could not be sent: …" (never the
  address). While one e-mail is on its way another is refused (409 `email_pending`).
- A mail server that is down is retried (1 min, 5 min, 30 min, …); a refused address is not.
- A quote e-mail is a business message, so it doesn't depend on marketing consent.
- If the worker crashes right after sending, the e-mail can go out twice (it is sent "at
  least once"); nothing is ever silently lost.

API: `POST /api/v1/quotes/{id}/email` with `{"version": n, "message": "..."}`; the quote read
model has `email_status` (`sending` / `sent` / `failed` / null).

API: `GET /api/v1/quotes/{id}/pdf`, `GET /api/v1/portal/quotes/{id}/pdf`.

## API (all under `/api/v1`)

| Method and path | What it does |
|---|---|
| `GET/POST /products`, `GET/PATCH /products/{id}` | list (search `q`, `active`), create, read, change/deactivate (managers change) |
| `GET/POST /price-books`, `GET/PATCH /price-books/{id}` | price books |
| `GET /price-books/{id}/prices`, `PUT/DELETE /price-books/{id}/prices/{product_id}` | prices in a book |
| `GET/POST /quotes`, `GET/PATCH /quotes/{id}` | list (filters `q`, `status`, `account_id`, `opportunity_id`, `order_id`, `owner_id`, `include_superseded`), create, read, edit draft |
| `POST /quotes/{id}/submit|approve|reject|send|accept|decline|revise|order` | workflow steps; each needs the current `version` |
| `GET /quotes/{id}/history` | the quote's history |
| `GET /portal/quotes`, `GET /portal/quotes/{id}`, `POST …/accept|decline` | customer portal |

Error codes: `quote_state` (step not allowed now), `quote_expired`, `invalid_quote`,
`related_not_found`, `version_conflict` (someone changed it first - reload),
`already_exists` (duplicate SKU or price book name), `product_not_found`,
`price_book_not_found`.

## Screens

- **Products** (`/products`): product list with search and active filter, price books on the
  side. Managers: *New product*, *New price book*, edit/deactivate a product, add/change/remove
  prices on a price book page.
- **Quotes** (`/quotes`): list with search and status; *New quote* with a line editor and live
  totals preview; quote page with the next-step buttons and the history.
- **Links:** the account page and the deal page have a *Quotes* card with *New quote*; an order
  made from a quote shows *From quote*.
- **Portal:** the portal home lists "Quotes waiting for your answer"; *Quotes* shows each quote
  with *Accept quote* / *Decline*.

## Database

Migration `20261019_0013_catalog_and_quotes`: `products`, `price_books`, `price_book_entries`,
`quotes`, `quote_lines`, `quote_events` (insert-only: UPDATE/DELETE revoked), and
`quote_number_counters`. All have `tenant_id`; money is `NUMERIC`.

## Not built yet

- E-mail templates per organisation (Communication Center, later).
- Bundles, volume prices and product images.
