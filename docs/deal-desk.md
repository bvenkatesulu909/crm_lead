# The deal desk and account research (CRM-114, ADR 0024)

Two AI helpers for salespeople. Both **read** the CRM as the person asking, and neither changes a
record:

- **Deal desk** (on a deal's page): three AI reviewers look at the deal at the same time - pricing,
  account and momentum - and a fourth, the **desk lead**, writes a short brief and may **suggest**
  at most two follow-up tasks. A suggested task waits in the approval queue until a **different**
  person approves it.
- **Account research** (on an account's page): a one-page brief about the account, in which every
  sentence names the record it comes from. It suggests nothing.

The design, the alternatives and the owner's eight decisions are in
[ADR 0024](adr/0024-deal-desk-and-account-research.md). The lead agent of
[ADR 0022](lead-agent.md) is a separate helper and stays as it is.

## 1. The deal desk, step by step

The steps are a small LangGraph graph (`backend/app/modules/deal_desk/graph.py`). Each step is a
plain function; the graph only decides the order, runs the three reviewers side by side, and limits
how many steps may run.

| Step | What happens | Can it change anything? |
|---|---|---|
| read | The deal - only if the person asking may read it (a sales agent: only their own deals). Then the agent registry: switched off or over budget stops here, before any model call. | No |
| fact sheets | Code (no model) builds three sheets through the other modules' `api.py`, as the person asking: **pricing** (amount, quotes, discount against the approval limit, quote validity), **account** (customer health, other open deals, a contract renewal within 90 days - or "You may not see this deal's account"), **momentum** (stage and how long it has been there, close date, next step, activity, overdue tasks, primary contact). Every fact is a code, a sentence and the record it comes from. Text a person typed (the next step) is cleaned and marked as data; words that read like an instruction to an AI add the fact `record_text_flagged`. | No |
| three reviewers | One model call each, **in parallel threads**, each seeing ONLY its own sheet and given ONE tool, `submit_findings` (at most 3 findings: severity act / watch / info, a sentence, the record ids it is based on). A reviewer that cites a record that is not on its own sheet, adds a field, or answers without the tool is **refused as a whole** for this run; the others still count. No database work happens in these threads. | No |
| desk lead | One model call that sees only the reviewers' findings (never the raw facts) and ONE tool, `submit_brief`: a brief of 3-5 sentences and at most **2** tasks (subject, due in 0-60 days, reason). More tasks or any extra field (a stage, an amount, a discount) refuses the whole brief. If no reviewer answered, the desk lead is not asked and nothing is stored. | No |
| propose | Each task becomes a pending `activity.create_task` proposal on the deal, through the safety check (the Sentinel, ADR 0017). A task whose reason holds a link or an instruction is refused and audited (`agent_action.blocked`); the others still wait. | No - only proposals |

Then the review (brief, findings, how each reviewer was judged, the proposal ids, tokens) is stored
in `deal_reviews` (insert-only, kept 12 months) and audited as `deal_desk.reviewed` with ids and
counts only - never what a model wrote.

## 2. Account research, step by step

| Step | What happens | Can it change anything? |
|---|---|---|
| read | The account - only if the person asking may read it; else "Account not found." and no model call. The registry is asked next (off / over budget: refused). | No |
| four gatherers | **sales** (the deals the person may read, invoiced value, last order), **service** (ticket figures, the next contract renewal), **conversations** (customer health, last interaction), **registry** (web checks already on file - it never starts one and never reads the internet). They read one after the other through one database session (a session cannot be shared between threads; each read takes milliseconds). | No |
| writer | ONE model call with ONE tool, `submit_account_brief`: at most 8 sentences, each with the record ids it is based on. A wrong shape refuses the whole answer. A sentence that cites nothing, or a record that was not gathered, is **removed** (the brief says how many). No sentence left: refused, nothing stored. Text is cleaned (links, pictures, hidden text out). | No |

The brief is stored in `account_briefs` (insert-only, kept 12 months) and audited as
`account_research.written`.

## 3. Who may use them

| | Deal desk (`deal_desk:run`) | Account research (`account_research:run`) |
|---|---|---|
| Sales agent | their own deals | their own accounts |
| Sales manager, tenant administrator | every deal of the organisation | every account |
| Support agent | no | every account (support reads all accounts) |
| Customer (portal) | no | no |

Anything the person may not read answers "not found" (404) - the same as a record that does not
exist.

## 4. Switches, budgets and limits

- Both are entries of the AI agent registry (Automation -> AI agents, ADR 0016): an administrator can
  switch each off, set a monthly token budget and take tools away; the platform switch
  `CRM_AI_DISABLED` stops both.
- The **deal desk is ON by default** for every organisation (owner's decision, 2026-11-08); **account
  research is OFF** until an administrator switches it on (ADR 0024, Q8).
- Limits, checked before any model call (429 when reached):

| Setting | Default |
|---|---|
| `CRM_DEAL_DESK_PER_DEAL_HOUR` | 1 review per deal per hour |
| `CRM_DEAL_DESK_PER_TENANT_DAY` | 200 reviews per organisation per day |
| `CRM_ACCOUNT_RESEARCH_PER_ACCOUNT_HOUR` | 1 brief per account per hour |
| `CRM_ACCOUNT_RESEARCH_PER_TENANT_DAY` | 200 briefs per organisation per day |

- A review is 4 model calls, a brief 1. The reviewers' tokens are counted after they finish (in one
  thread); a run that fails after a model call still counts the tokens it used.
- Free models may use the whole answer length on "thinking" and return nothing; on the one-server
  deployment `CRM_ASSISTANT_MAX_TOKENS` raises it (4096 is enough).

## 5. The API

| Call | Who | What |
|---|---|---|
| `POST /api/v1/deal-desk/reviews` `{"opportunity_id": ...}` | `deal_desk:run` | 201 with the review, its pending proposals and any safety-check refusals. 404 not readable, 403 not the owner, 503 switched off / over budget, 429 limit, 422 no usable answer |
| `GET /api/v1/deal-desk/reviews?opportunity_id=` | anyone who may read the deal | the newest 20 reviews |
| `POST /api/v1/account-research/briefs` `{"account_id": ...}` | `account_research:run` | 201 with the brief; same refusals |
| `GET /api/v1/account-research/briefs?account_id=` | anyone who may read the account | the newest 20 briefs |

The body takes only the record's id: no organisation, person or model text is ever accepted from
the client.

## 6. On screen

- **Deal desk** card on the deal page: the newest review as plain text, the findings by reviewer
  with links to the cited quote, account or contract, the suggested tasks with a link into the
  approval queue, and "Review this deal" for people who may ask on an open deal.
- **Account research** card on the account page: the newest brief, each sentence with a link to the
  deal it names, a note when sentences were removed, and "Research this account".
- The approval card says the task was suggested by "the deal desk".

## 7. How it is tested

- Pure rules: `tests/test_deal_desk_rules.py`, the review and research rules.
- Against the real database: `tests/db/test_deal_desk_facts.py`, `test_deal_desk_review.py`,
  `test_deal_desk_api.py`, `test_account_research_api.py` (happy path, role denial, record-level
  denial, tenant isolation, ID tampering, refused answers, a blocked proposal, the limits).
- The evaluation harness (BP-10, [agent-evals.md](agent-evals.md) section 6m):
  `backend/evals/agents/deal_desk.json` (17 cases) and `account_research.json` (11 cases), played
  through the real services with only the model scripted, plus checks no case can skip.
- Browser journey: `frontend/e2e/deal-desk.spec.ts`.
- One real-model run (DeepSeek, 2026-11-08): 8 of 13 live cases passed, with no safety failure; the
  other 5 differ only in wording and counts from the scripted answers ([agent-evals.md](agent-evals.md)
  section 6m, baseline `backend/evals/baseline/deepseek-deal-desk.json`).

## 8. What it does not do (on purpose)

- It never moves a stage, changes an amount or grants a discount - people decide those.
- Reviewers do not call CRM tools themselves: the fact sheets built by code keep each one inside the
  asker's permissions and make a run repeatable.
- Account research does not browse the internet or start a web check (ADR 0019).
- Nothing it suggests happens without a different person's approval.
