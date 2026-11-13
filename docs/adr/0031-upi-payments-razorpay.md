# ADR 0031 — UPI payments on invoices through Razorpay payment links (BP-17)

- **Status:** Accepted (2026-11-13, owner approved all six recommended answers in section 7).
- **Date:** 2026-11-13
- **Deciders:** Project owner
- **Depends on:** ADR 0007 (nothing real goes online before "go live"), ADR 0021 (one server), ADR 0005
  (outbox and worker), ADR 0006 (domain events), ADR 0025 (settings and secrets kept out of code)
- **Related:** BP-24 (UPI limits and mandate rules, a later design that must quote NPCI/RBI documents)

## 1. The problem

Today a payment on an invoice is typed in by a person after the money arrived somewhere else
(`payments` table, methods `bank_transfer`, `card`, `cash`, `other`). A buyer cannot pay from the CRM,
and the rep has to match bank statements by hand. In India most buyers pay by UPI.

## 2. What exists

- `invoices` module: issued invoices with `balance_due`, insert-only `payments` (a mistake is a reversal
  row), `record_payment` / `reverse_payment` services, audit entries, portal invoice pages.
- Outbox jobs with retries, domain events, notifications, per-tenant settings, forced RLS everywhere.
- No outside HTTP receiver other than the public chat; no webhook code; no payment provider.

## 3. What was checked about Razorpay (official docs, 2026-11-13)

- A webhook carries `X-Razorpay-Signature`, an HMAC-SHA256 of the **raw body** keyed with a webhook secret
  that is separate from the API key. Re-serialising parsed JSON breaks the match.
- Delivery is at least once; each delivery has `X-Razorpay-Event-Id`. Event-id dedup alone is not enough,
  because different events can concern the same payment: the business action itself must be idempotent.
- The receiver should verify, store durably and answer 2xx within about five seconds.
- The UPI-only payment link (`upi_link`) is **not supported in test mode** (a 400 with test keys). The
  standard payment link works in test mode and offers UPI among its methods.
- A link needs a `reference_id` unique per link, at most 40 characters.
- Not confirmed from the pages read: the exact `payment_link.paid` payload fields and whether `amount` is
  in paise. PL1 must read the current reference and test both before any code relies on them.

## 4. Decisions (proposed)

**UP1 — Standard payment links, test mode first.** The CRM asks Razorpay to create a payment link for the
balance of ONE issued invoice and shows the short URL. The buyer pays on Razorpay's own page (UPI, and the
other methods Razorpay offers). No card, UPI id or bank detail ever reaches or is stored by the CRM. Test
keys only until the owner says "go live"; the UPI-only link is not used, since it cannot be tested.

**UP2 — The webhook is the only thing that marks money received.** The browser coming back from the
payment page changes nothing. `POST /api/v1/integrations/razorpay/webhook` (public path, no token):
1. reads the **raw bytes**, checks the signature with a constant-time comparison, else 401 and nothing stored;
2. stores the event (event id unique, insert-only) and answers 200 at once;
3. a worker job turns a verified `payment_link.paid` event into a payment on the invoice through the
   invoices module's `api.py`, as the Automation identity, method `upi` or `card` as Razorpay reports it.

**UP3 — Idempotent in three places.** A duplicate event id is stored once. The payment carries the
Razorpay payment id as its `reference`, with a unique constraint per tenant, so a second event for the same
payment cannot add a second row. The amount is compared to the link's amount and to the invoice's balance:
a mismatch, a paid or cancelled invoice, or a currency other than INR is **not** applied; it is kept as a
"needs a person" event and notifies the invoice owner.

**UP4 — Server-controlled everything.** The client sends only an invoice id. The amount (`Decimal`, never a
float; paise only at the edge), the reference, the expiry (default 7 days) and the customer fields come from
the server. A link per invoice at a time; a new one cancels the old one at Razorpay. Who may create: those
who may record payments today (`can_record_payments`) and who may read the invoice; the portal customer
may **see and open** the link of their own invoice but not create it (decided in 4, question 3).

**UP5 — Which tenant.** The link's `notes` carry the tenant id and invoice id; the stored link row is the
truth. The webhook never takes a tenant from the body: it finds the link row by Razorpay's link id, and an
unknown link is stored as an unmatched event and applied nowhere.

**UP6 — Tables and settings.** `payment_links` (invoice, Razorpay link id, short URL, amount, status,
expiry; forced RLS) and `payment_events` (event id unique, type, raw body hash, verified, outcome; insert-only
with a retention delete lock like `web_evidence`). Settings `CRM_RAZORPAY_KEY_ID`, `CRM_RAZORPAY_KEY_SECRET`,
`CRM_RAZORPAY_WEBHOOK_SECRET` (placeholders in `.env.example`, never in code or logs), `CRM_RAZORPAY_MODE`
(`test` or `fake`; `live` refused unless the owner's go-live setting is on). A scripted fake provider runs
the whole flow in tests with no network. The feature is a registry entry (no model, **off by default**).

**UP7 — Refunds and reversals are not automatic.** A refund done at Razorpay is not mirrored in v1; a person
reverses the payment in the CRM as today. Documented as a limit.

**UP8 — Network.** The only outbound call is Razorpay's API host, through one small client with a timeout and
no redirects, and the only inbound path is the webhook. Caddy rate-limits the webhook path. The ADR 0019
fetcher is not used: this is a vendor API, not a page fetch, so it gets its own allow-listed client and its
own guard test.

## 4a. Corrections made while building UP1

- The webhook has no tenant until it finds the link, and row-level security hides every row without one.
  A narrow `SECURITY DEFINER` function `payment_link_tenant(link_id)` returns only the tenant id for a
  Razorpay link id (same pattern as ADR 0009's login lookup). An event for an unknown link has no tenant
  to own it, so it is **counted in a metric and not stored** (this replaces "stored as unmatched").
- `payment_events` is insert-only except two bookkeeping columns, `outcome` and `processed_at`, which the
  worker sets once; a trigger refuses every other change, and deleting a row younger than 365 days.

## 5. Phases

| Step | Content |
|---|---|
| UP0 | This ADR, owner's answers |
| UP1 | Migration, tables, settings, signature check, fake provider (pure and database tests, no endpoint) - **built 2026-11-13** |
| UP2 | Create link service and API, webhook receiver, worker job, notifications, audit |
| UP3 | Screens: "Pay by UPI" on the invoice (staff) and portal invoice, link status |
| UP4 | Playwright journey with the fake provider; test-mode check with the owner's Razorpay test keys |

## 6. Risks and limits

- Real money flows only after "go live"; until then Razorpay test keys or the fake.
- A webhook secret or key in a log would be serious: logs hold ids and outcome codes only.
- Limits and mandate rules for UPI (BP-24) are not coded here; if added they must cite NPCI/RBI documents.
- Partial payments: Razorpay links can allow them. v1 sets "partial payments off", so one link = one full balance.

## 7. Questions for the owner

1. Test mode with standard payment links (UPI shown among the methods) is acceptable, since the UPI-only link
   cannot be tested? (Recommended: yes.)
2. One full-balance link per invoice, no partial payments in v1? (Recommended: yes.)
3. May the portal customer open the link on their own invoice? Staff create it, the customer pays.
   (Recommended: yes.)
4. Refunds stay manual in v1? (Recommended: yes.)
5. Feature off by default in every organisation, switched on by a tenant administrator? (Recommended: yes.)
6. Do you already have a Razorpay account with test keys? Only you can create them; nothing is needed until UP4.
