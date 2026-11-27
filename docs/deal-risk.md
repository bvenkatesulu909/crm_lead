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

* **`deal_risk_snapshots`** (migration 0074): one row per forecast - level, score, rules version,
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

## The API (DR3) - `/api/v1/deal-risk`

All four need the permission `deal_risk:read` (managers and administrators); everyone else gets 403.

| Call | What it does |
|---|---|
| `GET /deal-risk?level=&limit=&offset=` | the newest forecast of every open deal you may read, highest score first (filtered and paged in SQL) |
| `GET /deal-risk/{deal}` | the newest stored forecast of one deal; 404 `deal_risk_not_computed` when none exists yet |
| `GET /deal-risk/{deal}/history?limit=` | earlier forecasts, newest first |
| `POST /deal-risk/{deal}/recompute` | works it out now and stores it (201); at most 30 per person per hour (`CRM_DEAL_RISK_RECOMPUTE_PER_USER_HOUR`), then 429 `deal_risk_rate_limited` |

Every answer carries a `note` saying it is an estimate, not a promise and not a probability. The
client sends nothing but the deal id in the path and the list filters: level, score and factors are
the server's. A deal you may not read, another organisation's deal, a closed deal and a made-up id
all answer 404.

## The screens (DR4)

Managers and administrators only (display only - the API decides again):

* **Deal page:** a **Deal risk forecast** card on an open deal - the level as a word, every reason
  with its points and source, what could not be read, how the level moved since the earlier
  forecast, when and how it was worked out, the estimate note and a **Work out the forecast** /
  **Update forecast** button (no AI). Nothing for a closed deal or for people without
  `deal_risk:read`.
* **Pipeline:** each deal card shows its level as a badge, and a **Risk forecast** filter keeps
  only deals whose newest forecast has that level (deals without a forecast drop out).
* **Dashboard:** two tiles, **Deals at high risk** (links to the filtered pipeline) and **Amount at
  risk** - a plain sum per currency of those deals' values, no conversion and no weighting.

## The optional AI coach (DR5)

`POST /api/v1/deal-risk/{deal}/coach` (managers and administrators; nothing but the deal id is
accepted). Registry entry **deal_risk_coach**, **off by default**: an administrator switches it on
under AI agents, with the usual monthly token budget, tool filter and platform switch.

* The coach sees **only the forecast the code worked out**: the level, the score and the reasons
  (codes, sentences built by code, points) and what could not be read. Never the deal's or
  customer's name, a contact detail, an id or text a person typed.
* It answers with ONE tool, `submit_advice`: at most **three** short pieces of advice and at most
  **two** follow-up tasks. Every piece must cite reason codes that really are in the forecast; a
  wrong shape, an unknown code, an instruction-like text or anything extra refuses the **whole**
  answer (422, nothing shown or proposed; the tokens used still count). Links and markup are taken
  out and the answer says so.
* Tasks only become **proposals** (`activity.create_task` on the deal, author `deal_risk_coach`)
  through the approval queue and its safety check; a different person approves. The proposal's
  reason is the CRM's own sentence for the cited reason, not model text.
* It never changes the score, the stage, the amount, a date, the owner or anything else.
* Limits: 1 per deal per hour, 200 per organisation per day (`CRM_DEAL_RISK_COACH_PER_*`), then
  429. A deal one may not read, a closed deal or a made-up id: 404 before any model is asked.
* Audit `deal_risk.coached` with the level, counts and proposal ids only.
* `CRM_AI_PROVIDER=fake` gives a scripted coach for local demos (refused in production).
* Migration 0080 teaches the approval queue the name. It follows 0079, the lead e-mail consent
  migration once main's duplicate 0073 is renumbered; it needs that fix first.

## Not built yet

A button for the coach on the deal page, BP-10 evaluation cases for the coach, the backtest (DR6). Signals not read yet:
close-date history, the number of contacts per deal, the account's overdue invoices and tickets beyond
what account health already says, and call notes (the rules support them; the reader passes none).
