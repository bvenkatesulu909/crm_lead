# ADR 0037 — Deal risk forecast: a transparent score with plain reasons

- **Status:** Accepted (2026-11-21, owner answered the questions of section 7: yes to 1-4 and 7-8, "too early" for 5, "manager" for 6)
- **Date:** 2026-11-21
- **Deciders:** Project owner
- **Depends on:** ADR 0024 (deal desk), ADR 0016 (agent registry), ADR 0014 (approval queue),
  ADR 0017/0018 (Sentinel, cleaning of untrusted text), ADR 0009 (row-level security),
  ADR 0035 (call notes, optional input)
- **Owner's feature list:** item 14, "Deal risk forecast".

## 1. The problem

A sales manager looks at a pipeline of open deals and asks: *which of these will probably not close on time,
and why?* Today the pipeline shows a stage and a fixed stage probability (`STAGE_PROBABILITY`), which says
nothing about the deal itself: a deal in "negotiation" that nobody has touched for six weeks looks the same as
one with a call booked tomorrow. The deal desk (ADR 0024) gives a written review on request, but nothing ranks
all deals or shows which ones are slipping.

A risk number is easy to get wrong in two ways: **an opaque number nobody can question**, and **a forecast
presented as a fact**. This ADR avoids both.

## 2. What exists

- `opportunities`: stage, amount (`Decimal`), currency, `expected_close_date`, owner, `next_step`,
  `closed_at`, `lost_reason`; `opportunity_stage_changes` (insert-only history).
- `deal_desk`: `facts.py` builds fact sheets as the person asking, through other modules' `api.py`
  (`sales_api.deal_facts`, `quotes_api.deal_quotes`, `activities_api.deal_activity`,
  `contracts_api.next_renewal`, `relationships_api.account_health`).
- `relationships/health.py`: the pattern to copy - a 0-100 score where **every point is a listed factor**.
- Activities (tasks, follow-ups, overdue), quotes (status, expiry, approval waiting), contracts, tickets.
- Agent registry (switch, budget, kill switch), approval queue + Sentinel (AI may only propose),
  forced RLS, audit, the BP-10 evaluation harness.

## 3. Decisions (proposed)

**DR1 - The risk is computed by code, as a list of reasons, not by a model.** A pure function
`assess(signals, now)` in a new module `deal_risk` returns a **risk level** (`low` / `medium` / `high`),
a **score 0-100** (higher = more risk) and a list of **factors**, each with a plain sentence, the points it
added and the record it comes from. Same signals = same answer, so it is testable and explainable. No model
sets the number. The weights live in code (documented in `docs/deal-risk.md`); tuning per organisation is a
later step (question 3).

**DR2 - Signals (all read as the person asking, through other modules' `api.py`):**

| Signal | Risk factor (examples) |
|---|---|
| Days since the last activity or interaction on the deal | no touch for 14 / 30 days |
| Open follow-up tasks overdue, or **no next step** and no open task | nothing planned |
| `expected_close_date` passed, or close date pushed back (from history) | slipped date |
| Days in the current stage vs. the organisation's typical (from its won deals) | stuck in stage |
| Stage went backwards, or moved forward with no activity | stage churn |
| Latest quote: expired, declined, discount awaiting approval for long | quote stalled |
| Account health `at_risk`, overdue invoices, tickets past SLA | account trouble |
| One contact only / no primary contact | single-threaded |
| Amount large against the organisation's usual deal | big deal, more to lose |
| Optional: call notes show unknown budget/timeline (ADR 0035) | key answers missing |

Missing data is shown as "not known", never counted as good news. A signal that cannot be read by the asker
(for example a record they may not see) is skipped and the answer says so.

**DR3 - Forecast versus fact, labelled everywhere.** *Facts* are things in the CRM (amount, stage, dates,
counts of overdue tasks). The *forecast* is the level, the score and the **"slip" line** ("likely to
close later than the expected date"). The screen always writes "Forecast (an estimate from the signals below,
not a promise)". The score is **not a probability** and is never multiplied into money. Money totals
("amount at high risk") are plain sums of the open deals' amounts per level, per currency, with no
currency conversion and no probability weighting.

**DR4 - Stored as an insert-only snapshot, so we can look back.** Table `deal_risk_snapshots`
(tenant, deal, level, score, factors as codes + numbers, computed_at, rule version). Forced RLS, no
UPDATE/DELETE for the application role, a trigger refuses edits, 365-day delete lock like the other history
tables. The worker recomputes the open deals of each organisation **nightly** (and a deal on demand, limited),
so the pipeline list is a cheap read. Snapshots let the manager see "was medium last week, high now" and let
us **measure the forecast against what really happened** (DR8).

**DR5 - Who sees what.** A new permission `deal_risk:read` (**sales managers and administrators only**, owner's answer to question 6;
sales agents do not see it in v1). The deal's own read rules decide the rest: a manager sees all deals in the
organisation, anything else is a 404. Lists are filtered in SQL. Support and portal customers never see it. Only the
reasons are shown; no personal data from other records is copied into a factor beyond a name the reader may
already see.

**DR6 - An optional AI step only explains and proposes; it never scores.** Optional, **off by default**, a
registry entry `deal_risk_coach` (uses a model; switch, monthly token budget, tool filter, platform switch,
ADR 0016). Given the computed factors (not raw records, no customer name or contact details), it writes **at
most three plain sentences** on what to do next and **may propose at most two follow-up tasks**
(`activity.create_task`, existing kind) through the approval queue and the Sentinel, approved by a different
person. It cannot change the score, stage, amount, date, owner or send anything. Its text is cleaned like every
model output, every cited factor must exist in the computed list (code check), and an answer that cites a
factor that does not exist is refused. The deal desk reviews (ADR 0024) can **read the stored risk** as one
more fact but do not change it.

**DR7 - The pipeline and deal screens.** The Kanban/list gets a risk badge (low/medium/high, with the word,
not only a colour) and a filter; the deal page gets a **Risk** card: level, score, the factors with their
sentences, "what changed since last week", the forecast label, and (if on) the coach's suggestions linking to
the approval queue. The manager's dashboard gets "deals at high risk" and "amount at risk" (per currency).
Display only: the API decides access.

**DR8 - Honesty check on the forecast (backtest).** A script and a report section compare past snapshots with
outcomes (won / lost / slipped past close date) so the organisation can see how often "high" deals were really
lost or late. If it is no better than the stage probability, the weights are revised (a new rule version, new
snapshots - old ones keep their version). Until there are enough closed deals (question 5) the card says
"too early to measure".

**DR9 - Limits, audit, no leaks.** On-demand recompute: 30 per person per hour. Audit entries
(`deal_risk.computed`, only for on-demand calls) hold ids, level and counts, never free text. Free text typed
by people (next step, notes) is never an input to the score; only its presence is. Nothing is fetched from
the web.

## 4. Alternatives considered

| Option | Why not (now) |
|---|---|
| A machine-learning model trained on past deals | A new organisation has too few closed deals; the result cannot be explained to a rep, and a wrong number looks authoritative. Possible later as an *extra* signal once the backtest (DR8) shows the simple rules are beaten. |
| Let an LLM read the deal and give a probability | Not reproducible, not auditable, can be steered by text in a note, and costs tokens for every deal every night. Rejected; the LLM only explains (DR6). |
| Only use the stage probability | That is today's weakness. |
| Extend customer health with deals | Health is about an *account*; a deal has its own clock (close date, stage age). Kept separate, but account health is one signal. |
| Compute on every page view | Slower and cannot show change over time. Snapshots (DR4) fix both. |

## 5. Steps (Phase DR), each ends with a stop for review

| Step | What | Done when |
|---|---|---|
| DR0 | This ADR + index line | Owner answers section 7 |
| DR1 | Pure rules `assess()` + the factor catalogue, with tests for each factor and for missing data | pure tests, deliberate breaks caught |
| DR2 | Migration `deal_risk_snapshots` (forced RLS, insert-only), the signal reader (through other modules' `api.py`, new read functions where needed), service, worker nightly job | database tests: tenant isolation, role and record-level denial, ID tampering |
| DR3 | API `GET /deal-risk` (list, filters, paging), `GET /opportunities/{id}/risk`, `POST .../recompute` | API tests |
| DR4 | Screens: badge, filter, Risk card, dashboard tiles; Playwright journey | Vitest + Playwright |
| DR5 | Optional coach: registry entry (off), governed run, proposals, BP-10 cases | evaluation cases pass; gate can fail |
| DR6 | Backtest script + report section, `docs/deal-risk.md` | run on demo data |

## 6. Risks

- **A wrong forecast being trusted.** Mitigated by reasons for every point, the "estimate" label, no money
  weighting, and the backtest.
- **Gaming.** Reps could log empty activities to lower risk. A factor looks at *activity kinds* and the
  manager sees the reasons.
- **Unfair use on individual reps.** Scores belong to deals, not people; no rep ranking in v1.
- **Cost / load** of the nightly job: bounded by open deals, plain SQL reads, no model.
- **Data quality** (stale close dates). Missing or old data is itself a visible factor.

## 7. Questions for the owner (answered 2026-11-21: yes, yes, yes, yes, too early, manager, yes, yes)

1. **Score by code, with reasons; no model deciding?** *Recommended: yes (DR1).*
2. **Show a level and a score, but never a percentage chance?** *Recommended: yes; the score is not a probability (DR3).*
3. **Fixed weights in v1, per-organisation tuning later?** *Recommended: fixed weights now.*
4. **Include the optional AI coach (off by default) in this phase?** *Recommended: yes, as the last build step (DR5); skip if you prefer to wait.*
5. **When may the screen claim the forecast works?** *Recommended: only after at least 30 closed deals in the organisation; before that it says "too early to measure".*
6. **Who sees risk?** *Recommended was: owners, managers and administrators. **Owner answered: "manager"** - read as sales managers and administrators only; agents, support and portal customers do not see it in v1. Say so if agents should see their own deals.*
7. **Include call-note gaps (ADR 0035) as a signal?** *Recommended: yes, only when call notes exist; absence is not penalised.*
8. **Nightly recompute plus on-demand, 365 days of snapshots kept?** *Recommended: yes.*
