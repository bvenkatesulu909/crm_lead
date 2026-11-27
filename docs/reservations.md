# Reservations: holding a unit with a token amount (ADR 0040, step RP2)

This is the second building block of UPI reserve-pay. A **reservation** is one buyer's hold on one
**unit** (see `docs/units.md`) for one **deal**. RP2 adds only the tables and the rules - there is no
API, no screen and no payment yet (RP3 onwards).

## The owner's rules (ADR 0040 section 6a), as code

| Rule | Where |
|---|---|
| The buyer has **24 hours** to pay the token | `rules.PAYMENT_WINDOW` |
| Once paid, the unit is **held for 7 days** (fixed) | `rules.HOLD_PERIOD` |
| Token = a fixed amount or a percentage of the price, kept between the organisation's **minimum and maximum**, never above the price, rounded to whole rupees | `rules.token_amount` |
| An amount outside the limits needs a manager's approval (RP7) | `rules.needs_exception` |
| Money that arrives late, or for a unit someone else took, is **owed back** - it never reserves anything | `rules.on_payment` |
| Refunds: seller cancels, unit withdrawn, late money or unit taken -> everything back; a buyer who cancels gets everything back inside the free window, then the price minus the part kept (to the paise) | `rules.refund_amount` |
| Nothing moves money - a person records a refund with the Razorpay refund id | `refund_reference` column |

Statuses: `pending_payment` -> `held` -> `converted`, with `expired`, `cancelled`, `refund_due`
and `refunded` around them. The allowed changes are in `rules.TRANSITIONS`; a paid hold can never
go back to waiting for payment or simply expire - the money is owed back instead.

## What the database itself refuses (migration 0087)

- A **second active reservation on the same unit** (`pending_payment` or `held`) - a partial
  unique index. This is "one buyer per unit at a time".
- Any status change outside the allowed list (a trigger).
- Changing the amount, unit, deal, rules version, creator or payment deadline after creation, and
  every DELETE (trigger, plus no DELETE/TRUNCATE for the application role).
- Impossible rows: a held reservation without a payment time, a refund due without an amount or
  reason, a refund larger than what was paid, a refunded row without a `rfnd_...` reference.
- Rule versions (`reservation_settings`) and the history (`reservation_events`) are insert-only.
- Forced row-level security on all three tables; a reservation can only point at a unit and a deal
  of the same organisation.

Tests: `backend/tests/test_reservation_rules.py` (pure) and
`backend/tests/db/test_reservation_tables.py` (real PostgreSQL).

## Open point for the owner

A hold that lapses after 7 days without becoming a booking is treated like a buyer's cancellation
(`hold_lapsed`: the refund policy applies). ADR 0040 does not say this outright; if the buyer should
get everything back in that case, it is a one-line change in `rules.py` before RP4 uses it.
