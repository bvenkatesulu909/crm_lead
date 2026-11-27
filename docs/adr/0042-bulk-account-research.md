# ADR 0042 — Research up to 100 accounts at once (a batch of account briefs)

- **Status:** Accepted (2026-11-21). The owner answered section 7: batch cap raised to 100, managers and administrators only, real saved filters first (BR-pre), confirmation required, "research again" tick, one account at a time, switch off by default, code-built table, no web look-ups, 12 months. The text below already reflects these answers.
- **Date:** 2026-11-21
- **Deciders:** Project owner
- **Depends on:** ADR 0024 (account research: one account, four code gatherers, one governed model call,
  an insert-only brief), ADR 0016 (agent registry, monthly token budgets, kill switch), ADR 0005 and 0006
  (outbox and worker, domain events), ADR 0019 (web check) and ADR 0026 (company details), ADR 0009
  (row-level security), ADR 0017 and 0018 (cleaning of untrusted text), ADR 0014 (nothing here changes
  CRM data), ADR 0034 and 0035 (the pattern: run as the person who asked, strict answers, insert-only records)
- **Amends:** nothing. ADR 0024's rules for one account stay exactly as they are; this ADR only adds a way to
  ask for many of them in one go.
- **Owner's feature list:** item 19, "Research 50 accounts at once".

## 1. The problem

Account research (ADR 0024) writes a one-page, sourced brief about **one** account. A sales manager preparing a
week - "all my accounts renewing this quarter", "the 40 accounts in the Hyderabad segment" - would have to open
40 pages and press 40 buttons, then read 40 pages. We want to say **"research these accounts"** once, see what it
will cost **before** anything runs, watch it progress, stop it if needed, and end up with **one brief per account
plus a table that lets the manager scan them all**.

The risks are the ones that appear whenever "one" becomes "many":

1. **Cost running away** (100 model calls from one click).
2. **Data crossing over** - account A's facts leaking into the model's view of account B, or into another
   organisation's call, or one poisoned record steering the others.
3. **A long job tied to a web request** (Netlify cuts requests at about 60 seconds) and half-finished states nobody
   can explain.
4. **Doing for 100 accounts what a person may not do for one** (read accounts that are not theirs, exceed the
   daily ceiling).

## 2. What exists and is reused

- `deal_desk` module: `run_research` (gather as the asker -> one governed model call -> sentences without a
  citation removed -> insert-only `account_briefs` row, audit `account_research.written`), permission
  `account_research:run`, registry entry `account_research` (off by default), limits 1 brief per account per hour
  and 200 per organisation per day, retention 12 months, a fake writer for `CRM_AI_PROVIDER=fake`.
- Outbox and worker (`outbox_jobs`, `python -m app.worker`): jobs carry ids only, retry with back-off (up to 3
  tries), are safe to run twice, are claimed under the application role; the worker binds a tenant and a person
  (`identity_api.bind_reader`) before it touches tenant data.
- Agent registry: switch, monthly token budget (`check_can_call`, atomic `record_usage`), platform switch,
  estimated cost from the two environment prices (`estimated_cost_usd`, a `Decimal`; CRM-111).
- Web evidence already on file (ADR 0019) and company details (ADR 0026) - the briefs only *show* what is
  already stored; neither starts a new check.
- Forced RLS on every tenant table, audit with ids and codes only, notifications by domain event, the BP-10
  evaluation harness (the desk runner in `agent_evals/desk.py` already plays account research with a scripted
  model).

## 3. Decisions (proposed)

**BR1 - A batch is a list of single researches, nothing smarter.** A new module `research_batches` owns two
tables and calls **`deal_desk.api.run_research`** once per account - the very same function the single button
calls, so every rule of ADR 0024 (gatherers read as the person, citations checked, no sourced sentence -> nothing
stored, cleaning, audit) applies unchanged. A module may import only another module's `api.py`; the batch module
therefore never touches `account_briefs` itself.

**BR2 - The cap is 100 accounts per batch.** Enforced in the API *and* by a database check on the batch row. More
than 100 is refused (422 `batch_too_large`), never silently cut. The number lives in a setting
(`CRM_RESEARCH_BATCH_MAX`, default 100; an organisation can lower it but not raise it above 100 without a new
decision).

**BR3 - Who may start a batch.** A new permission `research_batch:run` for **sales managers and tenant
administrators**. Sales agents, support agents and portal customers cannot (question 2 offers "agents, for their
own accounts"). Starting also needs the existing `account_research:run`. The batch **runs as the person who started
it**: the worker binds that person for every account, exactly like a single run, so research can never see more
than the person could read.

**BR4 - How accounts are chosen: what the person can see, resolved on the server.** Two ways, both ending in the
same server-side step:

- **a saved filter** of the Accounts list (a named, per-person or shared filter such as "Hyderabad, renewing this
  quarter"), or
- **ticked rows** on the list (up to 100 ids).

The server **never trusts the ids it receives**. It resolves the selection through the scoped accounts repository
and the record-level read policy **as the person**, takes at most 100 in the list's order, and stores that **frozen
list** (`research_batch_items`). Ids the person may not read, ids that do not exist and ids of another
organisation all get the same answer - *not available* - counted as "N not available" without saying which or
why. Archived accounts are skipped with a visible reason. Because the list is frozen at start, the batch does not
change if the filter's result changes later. *(There are no saved filters in the CRM today. The owner decided (question 3) that **real saved filters are built
first**, as their own small item, step BR-pre below; batches start only after it exists.)*

**BR5 - Fan-out is one account at a time, through the outbox.** Starting a batch writes the batch row and the
items in the starter's transaction and enqueues **one job** `research_batch.step` (payload: batch id and tenant,
ids only). Each run of the step: re-checks that the batch is still `running` and not cancelled, checks the budget
(BR7), **researches exactly one queued item**, writes its result, then enqueues the next step. So at any moment
there is at most one model call per batch, a stop takes effect within one item, a crashed worker resumes at the
next unfinished item, and running a step twice is harmless (an item already `done` is skipped). The worker's
existing retry covers temporary failures (up to 3 tries per item; only the last failure is recorded). Expected
time: about 10-15 s per account with a paid model, about 60 s with the slow free one (measured on staging for
ADR 0024) - so 100 accounts is roughly 20-100 minutes. That is acceptable because nobody waits on a web request;
the page polls.

**BR6 - Limits, in addition to ADR 0024's.**

- the existing **1 brief per account per hour** is kept; an account that already has a brief **younger than 24
  hours** is not researched again but **reused** (shown as `reused`, no model call, no cost); the person can tick
  "research again anyway", which then meets the hourly rule if the brief is too recent;
- the existing **200 per organisation per day** counts every item that really calls the model; a batch is refused
  at the start when the remaining daily allowance is smaller than the number of accounts that would call the model
  (429 `research_daily_limit`, with the number left in the message - the person narrows the selection);
- new: **1 running batch per person**, **at most 2 running batches per organisation**, **5 batches per person per
  day** (settings `CRM_RESEARCH_BATCH_*`).

Every refusal happens **before** any model call and before anything is queued.

**BR7 - The cost is shown before the run, and the budget stop is hard.**

1. *Estimate before.* `POST /research-batches/estimate` (no write, no model call) returns how many accounts will
   call the model, how many are reused or not available, an **upper bound of tokens** and the **estimated cost**
   from the existing `Decimal` price pair ("about $0.03 - an estimate, not a bill"). The upper bound is
   `accounts x worst case per account`, where the worst case is the writer's fixed input cap plus its output cap
   (`CRM_ASSISTANT_MAX_TOKENS`); a typical figure - the average of this organisation's last 20 briefs, or a
   built-in default when there are none - is shown next to it. The screen shows both, in words.
2. *The person confirms the figure they saw.* Starting sends the account count and the upper bound the screen
   showed; the server recomputes and refuses with 409 `estimate_changed` if they differ by more than 20 %, so a
   price or list change cannot slip in between.
3. *A cap on the batch.* The batch row stores `token_cap` = the confirmed upper bound, **also limited to what is
   left of the agent's monthly token budget** (ADR 0016). If the monthly budget is smaller than a worst-case
   batch, the screen says so before the run and offers a smaller selection.
4. *The stop.* Before **each** item the step checks `tokens_used + worst_case_per_item <= token_cap` **and** the
   registry gate (agent on, platform switch off, monthly budget). If either fails the batch ends as
   `stopped_budget`; the remaining items become `not_run`; finished briefs stay. Because the check uses the worst
   case of the *next* call, the cap cannot be exceeded even by the item that is running when it is reached.

**BR8 - Cancel.** "Stop" on the batch page sets `cancel_requested` (allowed for the starter and for any sales
manager or tenant administrator of the organisation). The next step sees it before starting an item; the item
already being researched finishes (a model call cannot be aborted) and is kept; the rest become `not_run`; the
batch ends `cancelled`. A cancelled or stopped batch is continued by starting a new batch from "Research the
accounts that did not run" (new estimate, new confirmation); nothing resumes by itself.

**BR9 - Progress and partial failure are shown item by item.** Each item has one status: `queued`, `running`,
`done`, `reused`, `skipped` (archived, or no longer readable when its turn came - access is re-checked per item),
`failed` (with a stable code shown in words: *no sourced sentence*, *the model's answer had the wrong shape*,
*unavailable*, *over budget*), `not_run`. The batch page shows a progress bar and counts ("31 of 100: 28 done, 2
reused, 1 failed"), the table below, and updates itself (polling every four seconds only while `running`, like the
proposal deck card). One failed account never stops the others. "Try the failed ones again" starts a new batch with
those accounts (new estimate, same rules).

**BR10 - Results are the individual briefs, plus a summary table made by code.** Each `done` item points to its
ordinary brief (`account_briefs`, unchanged), opened with the existing brief view. The **summary table** has one
row per account - name, outcome, number of sourced sentences, health, open deals and their count, last
interaction, next contract renewal, web evidence verdict, link to the brief - and is **assembled by code from each
brief's own stored facts** through a new read function in `deal_desk/api.py`, **not written by a model**. A column
the brief does not hold shows "-". It can be sorted and filtered on the page. (A CSV export of the table is
optional and goes through the existing reports export rules - formula-injection protection and an audit entry;
question 8.)

**BR11 - Isolation: no model call ever sees data from another organisation or from another account.**

- **One account per call.** Each item is a separate call of the single-account pipeline with its own fresh prompt
  built only from that account's fact sheets. There is **no shared prompt, conversation, memory or cache** between
  items and **no step that asks a model to compare or summarise several accounts** - the cross-account view is the
  code-built table of BR10.
- **One organisation per batch.** The batch row and its items carry the starter's `tenant_id` from the verified
  token (never from the client). The worker binds that tenant and person for every item; forced RLS makes another
  organisation's rows invisible even if an id were forged, and each item re-loads its account through the scoped
  repository (a mismatch is `skipped`, never researched).
- **Untrusted text stays inside its own call.** Record text goes through the usual cleaning and is marked as data;
  an instruction hidden in one account's notes can influence only that account's brief (which is cleaned and
  citation-checked) - there is no channel to the other 99 calls.
- **Tests prove it** (step BR5): scripted-model runs over a world with a poisoned account and accounts from two
  organisations assert that no prompt contains another account's name, id or text, and that a batch never
  contains an account of another organisation.

**BR12 - Governed like the rest of the AI features.**

- The model calls use the existing registry entry `account_research` (its switch, monthly budget, tool filter,
  platform switch; tokens are metered under it, so the AI agents page shows the true monthly cost). If it is off,
  a batch cannot start.
- A **new registry entry `research_batches`** (no model, **off by default**, like the web check and voice
  entries) lets an administrator switch bulk research off while single research stays on. The AI agents page
  counts "N batches this month".
- Audit entries `research_batch.started`, `.finished`, `.cancelled`, `.stopped_budget` with ids, counts and codes
  only (never account names or brief text). Metrics without a tenant label: `crm_research_batches_total{outcome}`
  and `crm_research_batch_items_total{status}`.
- On finish the starter gets one notification ("Research of 100 accounts finished: 46 done, 2 reused, 2 failed")
  linking to the batch page (event `research_batch.finished`, ids and counts only).

**BR13 - Data, retention, no deletes.** Two new tenant tables with **forced RLS**: `research_batches` (who, when,
status, counts, `token_cap`, `tokens_used`, the estimate shown, cancel flag, version) and `research_batch_items`
(batch, account id, position, status, failure code, brief id, tokens). Both are append-mostly: the application
role has **no DELETE**; updates are limited to the progress columns (a trigger refuses changes to the account
list, the starter, the cap and the tenant after creation). Rows are kept 12 months like briefs and swept by the
worker (a younger row cannot be deleted - a database trigger, as for `account_briefs`). A database check keeps the
counts consistent with the item statuses and limits the count to 100.

## 4. What this does not do

No selection by free text or by AI ("find my risky accounts"); no model that compares or ranks accounts; no
automatic or scheduled batches (a person presses the button); no new web checks or company-detail look-ups on the
accounts (the briefs only show evidence already on file, as in ADR 0024); no sending of anything to customers; no
change to any account, deal, task or lead (nothing here creates proposals); no batches over 100 and none across
organisations (platform staff included); no parallel model calls inside one batch; no saved filters.

## 5. Steps (Phase BR), each ends with a stop for review

Every step: a failing test first, deliberate breaks of each new protection, no secrets, migrations new and never
edited.

| Step | What | Done when |
|---|---|---|
| BR0 | This ADR and the index line (documents only) | Done: accepted 2026-11-21 (section 7) |
| BR-pre | **Saved filters on the Accounts list** (own small design and PR before BR1): save, name, share with the organisation or keep private, delete; stored as the list's own filter parameters only (validated against the list's allow-list, never SQL), per organisation, forced RLS | owner approves; batches can pick "a saved filter" |
| BR1 | Pure part: selection rules (cap, order, duplicates), the estimate (`Decimal`, upper bound, typical), the budget stop rule, the item status machine; migration `research_batches` + `research_batch_items` (forced RLS, locks, checks); read function `deal_desk_api.brief_overview` | rule tests; database tests for the checks, triggers, RLS, no DELETE; RLS guard and migrations-in-sync pass |
| BR2 | Service: `estimate`, `start` (resolves as the person, limits, 409 on a changed estimate, one transaction, audit), registry entry `research_batches`, permission `research_batch:run`, settings | database tests: role denial, tenant isolation, ID tampering (foreign, made-up and archived ids all "not available"), limits, estimate changed |
| BR3 | The worker step `research_batch.step` (one item per run, access and budget re-checked, cancel, `stopped_budget`, retries, safe to run twice, finish event and notification) with the fake writer | tests through the real worker: partial failure, cancel mid-run, hard cap with the worst-case rule, crash and resume, permission lost mid-batch |
| BR4 | API: `POST /research-batches/estimate`, `POST /research-batches`, `GET /research-batches` and `/{id}` (items, counts), `POST /{id}/cancel`, `POST /{id}/retry`; OpenAPI refreshed | API tests; strict bodies (tenant, person and status are never accepted) |
| BR5 | BP-10: a batch suite played through the real service with a scripted model (100 accounts; one poisoned; two organisations; one failing; cap reached; cancel; permission lost) and an **isolation check no case can skip** (no prompt contains another account's identifiers) | the gate fails when the check is broken on purpose |
| BR6 | Screens: a "Research selected accounts" bar on the Accounts list, the confirmation dialog (counts, not available, estimate, cap), the batch page (progress, table, cancel, retry, links to briefs), a line on the AI agents page; Playwright journey with the scripted writer; `docs/account-research-batches.md` | Vitest, Playwright, lint, typecheck; a look at the styled page from the main checkout |
| BR7 (optional) | CSV of the summary table (question 8) | export audited, injection protection tested |

Staging is not touched by any step; the entry stays off until an administrator switches it on.

## 6. Alternatives considered

- **One model call over all 100 accounts.** Rejected: the model would see every account at once - the cross-account
  leak and poisoning channel BR11 forbids - and quality drops with 100 accounts in one prompt.
- **One job fans out 100 parallel jobs at once.** Rejected: a cancel or a cap could not be hard (100 calls already in
  flight), and one database session cannot be shared between threads (ADR 0024 implementation note). Serial steps
  are slower but controllable.
- **Run synchronously inside the web request.** Rejected: Netlify and Caddy time-outs, and a closed tab would lose
  the work.
- **A model-written summary of all briefs.** Rejected for v1: it would be a cross-account model call. The
  code-built table gives the overview without it; a later ADR can add one if wanted.
- **Let sales agents batch their own accounts.** Not rejected - it is question 2 - only left out of the
  recommendation to keep early cost control with managers.
- **Nightly automatic research of every account.** Rejected: unbounded cost; a person decides what is worth
  researching.

## 7. Owner's answers (2026-11-21)

1. **Batch size:** **100** accounts (not 50); an organisation can only lower it. The org-wide daily ceiling of 200
   from ADR 0024 stays, so one full batch uses half of a day's allowance.
2. **Who may start:** sales managers and tenant administrators only.
3. **How accounts are chosen:** build **real saved filters first** (step BR-pre), then batch from a saved filter or
   ticked rows.
4. **Estimate and hard stop:** the person must **confirm** the estimate shown; the batch stops before any account
   whose worst case would pass the confirmed cap or the monthly budget.
5. **Recent briefs:** an account with a brief under 24 hours old is reused, with a "research again anyway" tick.
6. **Concurrency:** one account at a time per batch, one running batch per person, two per organisation.
7. **Switch:** new registry entry `research_batches`, **off by default**.
8. **Summary:** a table built by code (no model); CSV export stays optional (BR7).
9. **Web and company look-ups:** no; briefs show only evidence already on file.
10. **Retention:** 12 months, no deletes.

## 8a. Amendment (2026-11-22, while building BR1)

1. **The summary table reads what a brief stores.** A stored brief holds its cited sentences, how many were
   left out, how many facts each gatherer found and its tokens - not the health, open-deal count or renewal date
   that BR10 listed. So `deal_desk.api` gets two read functions, `latest_overviews` (newest brief per account,
   only accounts the person may read) and `overviews_of` (the overview of given briefs), and the v1 table shows
   those figures (sourced sentences, left out, facts per gatherer, tokens, date) beside the outcome and a link.
   Health, open deals and renewal stay on the brief's own sentences; richer live columns would be a separate,
   later decision because they cost more reads per account.
2. **A batch cannot change its own terms.** Besides the rules of BR13, the database refuses any change to the
   starter, source, account list, positions, confirmed estimate and cap, refuses `tokens_used` going down, and
   refuses a finished batch or item coming back to life.
3. **The hard cap is not a database check.** The stop is `tokens_used + worst case <= cap`, decided by the
   rules before every item (tests prove it for a whole run). A database check on `tokens_used <= token_cap`
   would only turn a miscounted call into a stuck batch.

4. **A fourth way to end (BR3):** `stopped_error`, for a batch that cannot go on - its starter is no longer an
   active member of staff, or its step job died after all its retries (migration 0079). The unstarted accounts
   become `not_run`. When the starter is gone the audit entry is written by the organisation's Automation
   identity, because the audit log always names an actor. `stopped_budget` covers every limit and switch: the
   batch's cap, the month's budget, the platform switch and either registry switch being turned off.
5. **The cap needs a stated worst case for the input.** The worst case of one account is the writer's output cap
   (`CRM_ASSISTANT_MAX_TOKENS`) plus `CRM_RESEARCH_BATCH_WORST_INPUT_TOKENS` (default 8,000). The cap is only as
   hard as that figure is true: BR3 measures every call from the month's usage (also a refused answer), and a
   later step should refuse an account whose prompt would exceed the input figure before the model is called.

## 8. Consequences

- A manager can prepare a whole segment in one action, knows the cost first, can stop at any time, sees which
  accounts failed and why, and keeps one sourced brief per account plus a table to scan them.
- Because every account is its own ordinary single-account call under the person's own permissions, nothing about
  access, citations, cleaning, budgets or the kill switches is new to reason about - the new parts are the
  selection, the cap arithmetic and the queue of items.
- New: module `research_batches`, two tenant tables (forced RLS), one permission (`research_batch:run`), one
  registry entry (no model), one worker job kind, two domain events, a BP-10 suite and one page. Costs and risks:
  bulk spend (capped as above); a long-running job needs the worker to be up (the page says "waiting for the
  worker" when nothing moves for 2 minutes); free models may keep what they receive, so demo data only, as for
  every agent.
