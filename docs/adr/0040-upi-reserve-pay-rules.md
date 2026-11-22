# ADR 0040 — UPI reserve-pay rules: taking a token / booking amount to hold a property

- **Status:** Accepted (2026-11-21, owner's answers recorded in section 6a; design only - no code, no tests)
- **Date:** 2026-11-21
- **Deciders:** Project owner
- **Depends on:** ADR 0031 (UPI payment links through Razorpay, test mode only), ADR 0014 (approval queue),
  ADR 0009 (row-level security), ADR 0016 (agent registry / switches), ADR 0032 (quotes and proposal decks)
- **Owner's feature list:** item 17, "UPI reserve-pay rules".

> **Read this first - a design question to confirm.** This ADR reads "reserve-pay" as *the rules for taking a
> small token or booking amount by UPI so a buyer can reserve a property or unit*. That reading is mine, not
> the ticket's. Also, **the CRM does not track units or inventory today** (checked in the code: there is no
> `units`, `inventory` or `projects` table; "apartment / villa / plot / commercial" is only a *wish* on a lead,
> `PROPERTY_TYPES` in `leads/models.py`). So "one unit held by one buyer at a time" has nothing to lock unless
> we add something. Question 1 decides this; everything else depends on it.

## 1. The problem

A buyer who likes a property is usually asked to pay a small **token / booking amount** to "hold" it while
paperwork happens. Today a rep does this by asking for a UPI transfer on WhatsApp and noting it by hand. The
CRM can already create a UPI payment link for an **invoice** (ADR 0031) and record the payment when Razorpay's
webhook says it arrived. What is missing is the *rules around reserving*: how much, for how long, what happens
if the buyer pays late or never pays, who gets money back and when, and making sure two buyers are not both
told "it is yours".

## 2. What exists (checked)

- `payment_links` module: one link per invoice, amount in **whole paise** (`BigInteger`, built from a `Decimal`),
  INR only, expiry, status, the signed webhook as the only thing that marks money received, a worker job that
  adds the payment to the invoice. Off by default (registry entry `payment_links`), Razorpay in **test mode
  only** until the owner says "go live". Refunds are manual and not mirrored (ADR 0031 UP7).
- `invoices` / payments, `quotes` (draft -> approved -> sent -> accepted/declined, discount approval),
  `orders`, `contracts`, `sales` (opportunities with stages, won/lost).
- Approval queue (a different person approves) and an audit log.
- **Not existing:** any inventory/unit/project record, any "hold" or "reservation" concept, any amount rule for
  tokens.

## 3. Decisions (proposed)

**RP1 - A reservation is its own small record, not just an invoice.** New module `reservations` (tables only
after Question 1): a reservation belongs to a **deal** (opportunity) and a lead or account, holds an amount
(`NUMERIC` / `Decimal`, never a float; whole paise only at the payment edge), a status and timestamps.
Statuses: `pending_payment`, `held`, `expired`, `cancelled`, `converted` (became the booking/order),
`refund_due`, `refunded`. Allowed changes are fixed in code and by database checks; the history is insert-only
(like the other money tables).

**RP2 - The payment uses ADR 0031 unchanged.** The reservation creates an invoice of a new kind ("token
amount") and the existing payment-link flow collects it. The webhook stays the only thing that says money
arrived; the browser coming back proves nothing. A reservation becomes `held` only when that payment is
recorded. No new Razorpay calls, no new keys, still test mode.

**RP3 - Amount rule: an organisation setting, with a hard ceiling.** Each organisation sets either a fixed
amount or a percentage of the deal/quote value (one or the other), plus a minimum and a maximum. The result is
computed on the server in `Decimal`, rounded half-up to the rupee, and **never taken from the client**. A
ceiling stops a typo turning a token into a full price; going beyond it is an exception (RP8). Whether a legal
cap applies is Question 5 (the owner's lawyer).

**RP4 - Hold period.** A reservation is `pending_payment` for a short **payment window** (default 24 hours,
setting, 1 hour to 7 days) matching the payment link's expiry, then `held` for a **hold period** (default 7
days, 1 to 30) counted from the payment. A worker sweep marks overdue ones `expired`; a read past the expiry
also treats it as expired, so a stopped worker cannot keep a unit held. Extending a hold is an exception (RP8).

**RP5 - One buyer per unit at a time (only if Question 1 adds units).** With a unit record, a partial unique
index allows at most one reservation in `pending_payment` or `held` per unit; a second buyer gets "already
reserved until <date>" and no payment link. Without units ("deal only") the rule is weaker and honest: *one
active reservation per deal*, and the screen says the CRM cannot stop the same property being promised on
another deal. We do not pretend to guarantee exclusivity we cannot enforce.

**RP6 - Unpaid, expired, late payment.**
- Unpaid at the end of the payment window -> `expired`, link cancelled, rep notified. Nothing to refund.
- **Payment arrives after expiry** -> never silently reserved. The reservation stays `expired`, the payment is
  recorded, and a "needs review" notification goes to the owner and a manager (same pattern as the existing
  `payment_link.needs_review`). If the unit is still free a manager may reinstate it (an exception);
  otherwise it becomes `refund_due`.
- Payment when someone else has since taken the unit -> `refund_due`, never `held`.

**RP7 - Cancellation and refunds follow a written policy; refunds stay manual.** The organisation writes a
simple policy: how long after payment the buyer may cancel for a full refund, and what part (a percentage, or
none) is kept after that. The CRM does the arithmetic (`Decimal`) and shows the amount due back, but **does not
move money**: marking `refunded` is a manual step by a finance person after the refund was made in the Razorpay
dashboard, with the Razorpay refund id typed in (shape checked, kept in the audit). If the seller cancels or
withdraws the unit, the whole amount is `refund_due`.

**RP8 - Who sets rules, who makes exceptions.** Settings (amount rule, windows, policy): tenant
administrators only (new permission `reservation:settings`), versioned and audited; a change never alters
reservations already made (each stores the rules it was made under). Creating a reservation: sales agents,
managers and administrators for deals they may read (`reservation:create`). **Exceptions go through the
approval queue and need a different person:** an amount below the minimum or above the ceiling, a hold
extension, reinstating after expiry, a refund that differs from the policy, cancelling a `held` reservation
after the free-cancel window. No AI creates or approves any of these in v1.

**RP9 - Conversion.** A `held` reservation can be linked to the booking: the accepted quote / order / contract
shows the token as an advance already paid (a payment line, not a discount), so the final invoice is the
balance. Only the server links them, and only if the deal and the amounts match.

**RP10 - Safety, as everywhere.** Forced RLS on every new table; the client sends only ids (deal,
reservation); amount, tenant, statuses, expiry and the Razorpay reference are server-controlled; typed notes go
through the shared text cleaning; audit entries hold ids and codes, not personal data; off by default behind a
registry switch; test mode only until "go live".

## 4. What this does not do

- It does not collect more than the token amount, nor set up instalments or EMIs.
- It does not refund, pay out or move money (a person records refunds).
- It does not give legal advice or decide what a lawful token amount is (Question 5).
- It does not build a property inventory unless Question 1 says so, and does not publish availability.
- It does not take cards, net banking or non-INR money. Live Razorpay keys stay off.

## 5. Steps (Phase RP), each ends with a stop for review

| Step | What | Done when |
|---|---|---|
| RP0 | This ADR accepted with the answers below | owner's word |
| RP1 | (Only if Question 1 = units) `units` module: project, unit, price, status; RLS; tests | units can be created and listed; none reservable yet |
| RP2 | `reservations` tables + pure rules (amount, windows, status changes, refund arithmetic) + migration; no endpoint | rule and database tests, RLS guard green |
| RP3 | Settings API + page (amount rule, windows, policy; versioned, audited) | an administrator can save; a manager cannot |
| RP4 | Create reservation -> token invoice -> existing payment link; webhook marks `held`; worker sweeps expiry | fake-provider test: pay -> held; no pay -> expired |
| RP5 | Late payment / taken unit -> needs-review and `refund_due`; notifications | a test for each branch |
| RP6 | Cancellation, refund-due arithmetic, manual "mark refunded" with reference | no automatic refund; amounts exact |
| RP7 | Exceptions as approval kinds (below minimum, extend hold, reinstate, off-policy refund) | a different person must approve |
| RP8 | Screens (deal card, reservation page, rules page) + Playwright journey with the fake provider | journey passes |
| RP9 | Conversion to order/contract advance; `docs/reservations.md`; the owner's lawyer reviews before any live use | docs done |

## 6. Questions for the owner (recommended answer first)

1. **Does the CRM need real units (project + unit + price + status), or is the rule only on a deal?**
   *Recommended: start "deal only" (one active reservation per deal; the screen says it cannot see other
   deals) and add units later in a separate ADR.* Units now means a whole inventory feature (import, price
   changes, hand-over) you did not list. If double-booking a specific plot or flat is the real pain, choose
   units - RP1 then comes first.
2. **Amount rule: a fixed amount, a percentage, or either per organisation?** *Recommended: either, one at a
   time, with a minimum, a maximum and a ceiling.*
3. **Defaults for payment window and hold period?** *Recommended: 24 hours to pay, 7 days held, editable by the
   administrator within the limits above.*
4. **If money arrives after the window or after someone else got the unit?** *Recommended: never reserve
   automatically; flag for a manager; refund due unless the manager reinstates.*
5. **Legal check.** Token/booking limits and refund duties differ by state and under RERA, and may also come
   from your own sale agreement. *Recommended: no legal value is hard-coded; the administrator sets them and
   **your lawyer confirms them before live use**. This ADR asserts nothing about what is lawful.*
6. **Refunds.** *Recommended: stay manual (as ADR 0031); the CRM computes the amount and records the
   reference.* Calling Razorpay's refund API would need live-mode review and its own decision.
7. **Who approves exceptions?** *Recommended: sales managers and administrators, never the person who asked.*
8. **Off by default per organisation?** *Recommended: yes, behind a registry switch, usable only after the
   payment-links switch is on.*

## 6a. Owner's answers (2026-11-21)

1. **Add units.** The CRM gets a `units` module (project, unit, price, status) and RP1 is built first; RP5's
   "one buyer per unit" rule is the real partial unique index, not the weaker deal-only wording.
2. **Minimum and maximum.** The administrator sets a minimum and a maximum token amount; the maximum is the
   ceiling (nothing above it without an approved exception). The fixed-or-percentage choice inside that range is
   unchanged unless the owner says otherwise.
3. **Hold period: 7 days only** (fixed, not editable). *Assumption to confirm:* the payment window stays a short
   fixed 24 hours; the answer was read as being about the hold period.
4. **Refund** (late money or a taken unit): the amount becomes `refund_due`; no automatic reinstating.
   *Reading to confirm:* the manager's "reinstate" exception in RP6 is dropped.
5. **Lawyer confirms** the values before any live use; nothing legal is hard-coded.
6. **Refunds stay manual**, as recommended.
7. **Managers** approve exceptions (never the person who asked).
8. **Off by default per organisation**, behind a registry switch.

## 7. Alternatives considered

- **Just a flag on the deal ("token paid")** - cheapest, but no hold period, expiry or refund arithmetic, and it
  repeats today's hand-noted problem. Kept only as the fallback shape if the owner wants less.
- **Put the hold on the quote** - a quote can be revised or declined and has no payment concept; a reservation
  outlives revisions. Rejected.
- **A plain invoice with no reservation record** - cannot express expiry or one-at-a-time. Rejected.
- **Automatic refunds through Razorpay's API** - convenient, but moves money without a person and needs
  live-mode work. Rejected for v1.
- **Full inventory first** - right for exclusivity but large; offered as Question 1's second option.

## 8. Risks

- **Money and law:** a careless default could encourage an excessive or unlawful token. Mitigated by no
  hard-coded legal values, a ceiling, approvals for exceptions and a lawyer's sign-off before live use.
- **False exclusivity** without units: a buyer may believe a unit is theirs. Mitigated by plain wording on the
  screen (RP5) and by Question 1.
- **Webhook timing:** late or duplicate events. Mitigated by the existing idempotent webhook and RP6.
- **Stopped worker:** holds stay open longer. Mitigated by treating a read past the expiry as expired (RP4).
- **Refund records drifting from Razorpay:** manual by design; the audit trail and the typed refund reference
  are the control.

## 9. Consequences

More structure around the most sensitive moment in a sale, no new outside service, and no change to how money is
received. If Question 1 is "units", this becomes two phases and the inventory part needs its own review.
