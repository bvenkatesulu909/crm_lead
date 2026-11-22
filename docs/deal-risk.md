# Deal risk forecast

Design: [ADR 0037](adr/0037-deal-risk-forecast.md). This page says what is built so far.

## What it is

For every **open** deal, code works out a **level** (low / medium / high), a **score** from 0 to 100
(higher = more risk) and a **list of reasons**. Each reason has a code, a plain sentence, the points
it added and the kind of record it comes from. There is no model in this path, so the same facts
always give the same answer.

* It is a **forecast, not a fact**: an estimate from the listed signals, never a promise.
* The score is **not a probability** and is never multiplied into money.
* A signal that cannot be read (or that we do not have) is listed as **unknown** and adds no points;
  missing data is never counted as good news.
* Levels: **medium from 30 points, high from 60** (fixed in v1).

## The rules (DR1) - `app/modules/deal_risk/rules.py`

| Code | Reason | Points |
|---|---|---|
| `no_touch_14` / `no_touch_30` | nothing logged on the deal for 14 / 30 days | 12 / 25 |
| `overdue_tasks` | overdue follow-up tasks (5 each, at most 15) | 5-15 |
| `nothing_planned` | no next step written and no open task | 12 |
| `close_date_passed` | the expected close date is in the past | 20 |
| `close_date_pushed` | the close date moved later (6 each, at most 15) | 6-15 |
| `stuck_in_stage` | twice as long in the stage as won deals usually take | 15 |
| `stage_went_back` / `forward_without_activity` | stage churn | 10 / 8 |
| `quote_expired` / `quote_declined` / `quote_stalled` / `no_quote` | the latest quote | 15 / 20 / 10 / 8 |
| `account_at_risk` | the account's health is "at risk" | 12 |
| `overdue_invoices` / `tickets_past_sla` | trouble on the account | 8 / 6 |
| `no_primary_contact` / `single_threaded` | people on the buyer's side | 8 / 6 |
| `large_deal` | at least twice the usual (median) won deal in that currency | 5 |
| `key_answers_missing` | the last call notes left two or more checklist lines unanswered | 6 |

## What is stored and read (DR2)

* **`deal_risk_snapshots`** (migration 0073): one row per forecast - level, score, rules version,
  factors (codes, sentences, points), the unknown signals, `source` (`nightly` or `on_demand`) and,
  for on-demand, who asked. Row-level security (forced), and **insert-only**: a trigger refuses every
  UPDATE and a DELETE of a row younger than 365 days, and the application role has no UPDATE or
  TRUNCATE. The database also checks the level, the score range and that a nightly row has no asker.
* **Signals** are read as the person asking through the other modules' `api.py`
  (`sales_api.risk_inputs`, `activities_api.deal_activity`, `quotes_api.deal_quotes`,
  `relationships_api.account_health`, `sales_api.won_history`). Free text such as the next step is
  reduced to "is there one".
* **"Usual"** (typical days in a stage, typical deal size) is the median of the organisation's recent
  won deals, and only when there are at least **5** of them; otherwise it is unknown.
* **Who may ask**: the permission `deal_risk:read` - sales managers and administrators only in v1 -
  plus the deal's own read rules. A deal one may not read, a made-up id, a closed deal or another
  organisation's deal all answer "not found".
* **The worker** (`run_schedules`) takes about one snapshot per open deal per day as the
  organisation's Automation identity, skips a deal already done in the last 20 hours (so it is safe to
  call every minute) and deletes snapshots older than 365 days.
* **Audit**: an on-demand forecast writes `deal_risk.computed` with the level, score and number of
  factors only.

## Not built yet

API and screens (DR3, DR4), the optional AI coach (DR5), the backtest (DR6). Signals not read yet:
close-date history, the number of contacts per deal, the account's overdue invoices and tickets beyond
what account health already says, and call notes (the rules support them; the reader passes none).
