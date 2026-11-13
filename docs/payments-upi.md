# UPI payments through Razorpay payment links

Design and decisions: [ADR 0031](adr/0031-upi-payments-razorpay.md). This page says what is built and how
to use it. Status: **UP1-UP3 built** (backend and screens); the check with real Razorpay test keys (UP4) is
not done yet.

## 1. What it does

1. A person who may record payments (tenant administrator, sales manager) asks for a **payment link**
   for an issued invoice. The CRM asks Razorpay to create a standard payment link for the balance that
   is still owed and stores its short address.
2. The buyer opens the link and pays on Razorpay's own page (UPI among the methods). Card or UPI details
   never reach the CRM.
3. Razorpay tells the CRM through a **signed webhook**. Only a verified webhook can mark money
   received. The browser coming back from the payment page changes nothing.
4. A worker job adds a payment (method `upi`, the Razorpay payment id as its reference) to the invoice
   and tells the person who made the link. If something does not fit (wrong amount, another currency,
   the invoice was already settled) nothing is recorded and the people who record payments are told.

## 2. Switching it on

The feature is a registry entry, **UPI payment links**, off by default for every organisation. A tenant
administrator switches it on at *Automation → AI agents* (the entry uses no language model). Switching it
off stops new links; payments already on their way are still recorded.

Settings (all `CRM_` variables, placeholders in `backend/.env.example`):

| Setting | Meaning |
|---|---|
| `CRM_RAZORPAY_MODE` | `off` (default: no provider, links cannot be created, the webhook refuses everything), `fake` (no network, tests and demos; refused in production), `test` (Razorpay test keys) or `live` (also needs `CRM_RAZORPAY_GO_LIVE=true` and a live key) |
| `CRM_RAZORPAY_KEY_ID` / `_KEY_SECRET` | the API key pair; never logged |
| `CRM_RAZORPAY_WEBHOOK_SECRET` | the webhook's own secret (not the key secret) |
| `CRM_RAZORPAY_LINK_EXPIRY_DAYS` | how long a link works (default 7) |
| `CRM_RAZORPAY_LINKS_PER_USER_HOUR` | links one person may create per hour (default 30) |

The webhook address to give Razorpay is `https://<api host>/api/v1/integrations/razorpay/webhook`, for the
events `payment_link.paid`, `payment_link.expired` and `payment_link.cancelled`. Other events are
acknowledged and dropped.

## 2a. Screens

- **Staff, invoice page:** a **Pay by UPI** card (right column) for an issued invoice in INR with money
  owed. It shows the open link (address as plain text, amount, expiry, *Open payment page*, *Copy link*),
  the earlier links in one line each, and a button *Create UPI payment link* (or *Create a new link
  (replaces this one)*) for people who may record payments. The API's refusals are shown in plain
  words, e.g. when the feature is switched off. After creating, the page shows "The UPI payment link was
  created."
- **Customer portal, invoice page:** while a link is open, a **Pay by UPI** button (opens Razorpay's page in
  a new tab) with a note that the CRM never sees the UPI details and that the payment can take a few
  minutes to show.
- Only an https address is ever shown or opened; the amount comes from the server; the browser sends only
  the invoice id.
- **INR** is now offered in the order form's currency list (it was missing); invoices follow their order's
  currency.

## 3. API

| Call | Who | What |
|---|---|---|
| `POST /api/v1/payment-links` `{invoice_id}` | `payment:record` | create a link; replaces the invoice's open link |
| `GET /api/v1/payment-links?invoice_id=` | invoice readers | the links of an invoice, newest first |
| `GET /api/v1/portal/payment-links?invoice_id=` | portal customers | the open link of their own invoice, or nothing |
| `POST /api/v1/integrations/razorpay/webhook` | Razorpay (no sign-in) | signed events |

Only the invoice id is sent. The amount, reference and expiry are decided by the server, and the tenant
comes from the verified token (or, for the webhook, from the stored link).

## 4. Rules that protect the money

- **Signature first.** The webhook checks the HMAC-SHA256 of the raw bytes before reading anything; no
  secret on the server means every delivery is refused. Bodies over 64 KB are refused.
- **Three places stop a double payment:** the event id is stored once; the gateway payment id is a unique
  reference per organisation (checked in the service and by a database index); and an event with an
  outcome is never applied again.
- **Amount and currency must match the link.** A different amount or currency, an invoice that no longer
  has a balance, or a part payment made meanwhile that leaves too little: nothing is recorded; the people
  who record payments get a notification.
- **Only INR invoices.** The demo data's default currency is EUR; an invoice in another currency answers
  409 "UPI payments are for invoices in INR".
- **No customer data is sent to Razorpay or copied out of its events** (no e-mail, phone or UPI id).
- **An unknown link is acknowledged and counted** (`crm_payment_webhooks_total{result="unknown_link"}`),
  not stored: it has no organisation to belong to.

## 5. Limits of version 1

- One full-balance link per invoice at a time; no part payments.
- Refunds done at Razorpay are not mirrored: a person reverses the payment in the CRM as today.
- A link created at Razorpay whose database save fails later is an orphan; paying it is acknowledged as
  "unknown link" and a person must reconcile it.
- Razorpay's field names for the standard payment link (`amount` in paise, `expire_by`, `accept_partial`,
  `reference_id`, `notes`) are taken from its public documentation and covered by tests against a fake
  transport; they are **verified against Razorpay's test mode only in UP4**.
- Caddy does not rate-limit the webhook path (the stock proxy has no such module); the signature check
  is cheap and the body is capped.
