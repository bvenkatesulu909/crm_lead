# ADR 0024 — Deal desk: several AI reviewers on one deal, plus parallel account research (CRM-114)

- **Status:** Accepted (2026-11-08) with the recommended answers to all eight questions in section 6
- **Date:** 2026-11-08
- **Deciders:** Project owner
- **Depends on:** ADR 0014 (approval queue), ADR 0016 (agent registry, budgets, kill switch),
  ADR 0017/0018 (Sentinel, injection defences), ADR 0019 (web check), ADR 0022 (the lead agent and
  its LangGraph rule)

> **Honest note about the source.** The ticket list names CRM-114 *"Multi-agent deal desk, plus
> parallel account research"*. The ticket text itself is not in the repository. On 2026-11-04 an
> older title (*"optional: lead agent in LangGraph"*) was used instead and ADR 0022 built one lead
> agent. That agent stays as it is. This ADR covers what the newer title asks for, and everything in
> sections 1-3 is **my reading of that title**. Correct it in question Q1 before any code is written.

## 1. The problem (reading of the title)

**Deal desk.** In a sales team, a "deal desk" is the group that looks at a deal before it is pushed
forward: is the price inside the rules, is the customer healthy, is the deal stuck, is anything
missing? Today a sales manager does this by opening the deal, the account, the quotes, the tickets,
the invoices and the activities one by one. Nobody does it for every deal.

**Account research.** Before a meeting a salesperson wants one page about a customer: what we have
sold them, what is open, what went wrong, what our documents say about them, and what the registry
checks found. Today that means reading six screens.

**"Multi-agent" and "parallel".** Several narrow AI reviewers each look at one side of the deal at
the same time (in parallel), and one more step merges their findings into one short brief. Each
reviewer sees only its own facts and has one job, which makes it easier to test and harder to
mislead than one model that sees everything.

## 2. What already exists and is reused

| Need | Already in the CRM |
|---|---|
| Deals | `sales` module: opportunities with stage, amount (`NUMERIC`), expected close date, next step, owner, stage history |
| Prices and discounts | `quotes` module: price book, discount over the organisation's limit needs a manager (four-eyes) |
| Customer health | `relationships` module: customer health and the at-risk list |
| Open problems | `support` (tickets), `invoices` (overdue), `contracts` (renewal dates) |
| What we wrote to the customer | `communications` (e-mail history) |
| Our documents | `knowledge` (cited answers, RERA gate - CRM-115) |
| Registry checks | `webcheck` (stored evidence only; ADR 0019) |
| Safe changes | `approvals`: an AI only **proposes**, a different person approves; the Sentinel checks every proposal |
| On/off, budget, metering | agent registry (ADR 0016), `agent` label on the AI metrics (CRM-111) |
| Several steps with a shared state | LangGraph, already pinned and allowed in one module (ADR 0022) |

## 3. The decision (proposal)

### 3.1 Deal desk

A **"Review this deal"** button on an open deal's page (and the same call for the staff assistant
later). One review runs as a small LangGraph graph in a new module `deal_desk`:

```
                    ┌─> pricing reviewer ──┐
read the deal ──────┼─> account reviewer ──┼──> desk lead (merge) ──> store review ──> at most 2 proposals
 (as the asker)     └─> momentum reviewer ─┘                                          (approval queue)
```

1. **Read** - the deal, only if the person asking may read it (else 404, no model call). Each
   reviewer gets a **fact sheet** built by code, not by a model: numbers, dates, codes and short
   cleaned texts, each with the id of the record it came from.
2. **Reviewers, in parallel** (LangGraph fan-out). Each one is one model call with **one tool**,
   `submit_findings`: up to 3 findings, each a severity (`info` / `watch` / `act`), a short text and
   the ids of the records it is based on (only ids from its own fact sheet are accepted).
   - **Pricing**: the deal's quotes against the price book, discounts near or over the approval
     limit, a quote that expires before the expected close date, an amount that differs from the
     accepted quote.
   - **Account**: customer health, open tickets, overdue invoices, a contract renewal soon, other
     open deals with the same account.
   - **Momentum**: days in the current stage, an expected close date in the past, no next step, no
     activity for N days, no primary contact.
3. **Desk lead** - one more model call that sees **only the reviewers' findings** (not the raw facts)
   and writes a 3-5 sentence brief plus **at most 2** proposals through the approval queue.
4. **Store** - the review (brief, findings, cited ids, model names, tokens) in an insert-only table.
   The deal page shows the newest review; every finding links to its records.

**What it may propose (v1):** only a **follow-up task on the deal** (the existing
`activity.create_task` kind, widened to the target type `opportunity`). It never moves a stage,
marks a deal won or lost, changes an amount or grants a discount: those stay human decisions, and a
discount already has its own four-eyes rule.

### 3.2 Parallel account research

A **"Research this account"** button on an account page. A second graph in the same module:

```
                     ┌─> sales history   (deals, quotes, orders, invoices) ─┐
read the account ────┼─> service history (tickets, satisfaction, contracts) ┼──> writer ──> store brief
 (as the asker)      ├─> conversations   (e-mails, activities)              ┤
                     └─> documents and registry evidence already on file ───┘
```

The four gatherers are **code, not models** (they only read through each module's `api.py`, under
the asker's permissions) and run in parallel. One model call (the writer) turns the gathered facts
into a one-page brief with a citation for every sentence; a sentence without a citation, or citing a
record that was not gathered, is removed (the same rule as the cited knowledge answers). The brief
proposes nothing.

It does **not** browse the internet and does **not** start new web checks: it only shows the
registry evidence already on file and says "no check on file" otherwise (ADR 0019: no model reads a
page).

### 3.3 Rules shared by both

- Two new registry entries, **`deal_desk`** and **`account_research`**, **off by default** (the deal
  desk changed to ON by default on 2026-11-08, see the change after section 6); the
  switch, monthly token budget and the platform switch apply; tokens are metered per agent.
- Who may: the deal desk - the deal's owner, sales managers and tenant administrators; account
  research - anyone who may read the account. New permissions `deal_desk:run`, `account_research:run`.
- Limits before any model call: one review per deal per hour, one brief per account per hour, a
  daily ceiling per organisation (settings, 429 when reached).
- Everything a model writes is cleaned (links, pictures, hidden text out) and shown as plain text;
  record text in fact sheets goes through `clean_records` and is marked as data, never instructions.
- New tables `deal_reviews` and `account_briefs`: tenant-owned, forced RLS, insert-only, kept 12
  months (worker sweep). Audit `deal_desk.reviewed` / `account_research.written` with ids and codes.
- LangGraph stays inside `app/modules/deal_desk/graph.py` (the guard test of ADR 0022 is widened to
  allow exactly that second file).

### 3.4 Cost

A deal review is **4 model calls** (3 reviewers + desk lead), an account brief **1**. With
`deepseek-chat` prices that is well under one US cent per review (estimate; measured in step DD6).
With free OpenRouter models it costs nothing, but free models may keep what they receive: demo data
only, as for the other agents.

## 4. Alternatives considered

| Option | Why not (or not yet) |
|---|---|
| One big model call with all the facts | Cheaper (1 call), but not "multi-agent", harder to test one side at a time, and one poisoned record can steer the whole answer. Offered as Q4-B. |
| Let reviewers call CRM tools themselves | More "agentic", but the fact sheet built by code is what keeps each reviewer inside the asker's permissions and makes runs repeatable. |
| Let the deal desk move stages or grant discounts | Those are business decisions with rules of their own; an AI proposing them invites rubber-stamping. |
| Let account research browse the web | Breaks ADR 0019 (no model reads a page; only fixed registry sources). |

## 5. Steps (Phase DD), each stops for review

| Step | Content |
|---|---|
| DD0 | This ADR + the phase plan (documents only) |
| DD1 | Module `deal_desk`: fact sheets for the three reviewers built by code through each module's `api.py` (no model); tests for permissions, tenant isolation, record-level denial, ID tampering |
| DD2 | The graph: parallel reviewers, desk lead, strict answer checks, citations limited to the fact sheet; registry entry `deal_desk` (off); migration (`deal_reviews`, `activity.create_task` on `opportunity`); limits; audit |
| DD3 | `POST /deal-desk/reviews`, `GET /deal-desk/reviews?opportunity_id=`, the "Review this deal" card on the deal page; scripted model for `CRM_AI_PROVIDER=fake` |
| DD4 | Account research: four gatherers, the writer, `account_briefs`, registry entry `account_research` (off), API and the account page card |
| DD5 | BP-10 cases for both (a poisoned record, a colleague's deal, a reviewer citing a record it was not given, more than 2 proposals, a stage-move proposal refused, switch off, budget, limits); Playwright journey - **done 2026-11-08**: 17 deal desk + 11 account research cases (`backend/evals/agents/deal_desk.json`, `account_research.json`, docs/agent-evals.md 6m), `e2e/deal-desk.spec.ts` now covers both |
| DD6 | Docs (`docs/deal-desk.md`), one real-model run (with the owner's yes), full runs - docs done 2026-11-08; the real-model run waits for the owner's yes |

## 6. Questions for the owner (recommended answer first)

- **Q1 - Reading of the ticket.** Deal desk = three AI reviewers + a desk lead on one deal; account
  research = parallel gathering over the CRM's own data + one writer. **Recommended: yes, as
  written.** If the ticket meant something else (for example agents that negotiate prices or talk
  to customers), say so now.
- **Q2 - Reviewers in v1.** **Recommended: pricing, account, momentum.** A fourth "compliance"
  reviewer (RERA evidence, brochure facts) can follow once real registry sources exist.
- **Q3 - What the deal desk may propose.** **Recommended: follow-up tasks on the deal only, at most
  2 per review.** Alternative: also propose "next step" text changes. Never stages, amounts or
  discounts.
- **Q4 - Real multi-agent or one call.** **A (recommended):** 3 reviewers + desk lead (4 calls), the
  real multi-agent pattern the ticket names. **B:** facts gathered in parallel, one model call (cheaper,
  simpler, but not multi-agent).
- **Q5 - Account research and the web.** **Recommended: only evidence already on file, no new web
  checks** in v1. Alternative: offer a "check now" button that queues the normal web check (its own
  limits and switch).
- **Q6 - Who may run it.** **Recommended:** deal desk for the deal's owner, sales managers and tenant
  administrators; account research for anyone who may read the account.
- **Q7 - Keeping reviews and briefs.** **Recommended: 12 months, insert-only**, like web evidence.
- **Q8 - Default.** **Recommended: both off by default** in the agent registry; a tenant
  administrator switches them on.

### Decision (2026-11-08)

The owner accepted every recommended answer: Q1 the reading as written; Q2 pricing, account and
momentum reviewers; Q3 follow-up tasks on the deal only, at most 2; Q4 A (3 reviewers + desk lead);
Q5 evidence on file only, no new web checks; Q6 deal owner, sales managers and tenant administrators
for the deal desk, anyone who may read the account for research; Q7 12 months, insert-only; Q8 both
off by default.

### Change (2026-11-08): the deal desk is ON by default

After trying it on staging the owner changed Q8 for the deal desk: **every organisation starts with
it switched on**, including organisations created later; an administrator can still switch it off
under AI agents (the switch, budget, limits and approval rules are unchanged). Account research
(DD4) is not decided by this change and still starts off.

### Implementation note (2026-11-08, step DD4): the gatherers read one after the other

The four gatherers are independent, but they read through the request's ONE database session, and a
session must not be shared between threads. Their reads take milliseconds, so they run one after the
other; the slow part, the writer's model call, is a single call. Only work that waits on a model runs
in parallel threads (the deal desk's three reviewers). The gatherers only show registry checks that
are already on file; account research starts none.

## 7. What this does not change

ADR 0022's lead agent, the Qualifier, the approval queue's rules (a different person approves) and
the Sentinel stay as they are. Nothing goes online with this ADR; "go live" remains the owner's
decision.
