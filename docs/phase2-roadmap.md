# AI Track A2 - "Governance, Sentinel Firewall, Spec-First Artifacts & Citation-Locked RAG"

- **Status:** roadmap only (2026-10-25). **Nothing here is started.** Each object follows your
  rule: design first, you approve, then small steps, one at a time, a stop for review after each.
- **Order (master plan):** BP-14 → BP-21 → BP-29 → BP-09 → BP-08 → BP-15 → BP-20.
- **Starts after:** BP-10 (agent evaluation harness) and BP-11 (CRM MCP server), as you decided.
- **Source:** `docs/master-plan.md`, AI Track A2.

## What this phase is for, in plain words

| Theme | Question it answers | Objects |
|---|---|---|
| **Governance** | Which AI features exist, who owns them, how much may they spend, and can I switch one off *now*? | BP-14, BP-09 |
| **Sentinel firewall** | Can a poisoned lead note, e-mail or web-form text steer an AI into a bad proposal? | BP-21, BP-29 |
| **Spec-first artifacts** | For every AI proposal, can I see what was checked and what would change, before I approve? | BP-29 |
| **Citation-locked RAG** | Does a property or RERA answer always point to a source - or say "I don't know"? | BP-08, BP-15 |
| **Safety net in CI** | Do dependency, secret and money-type mistakes fail the build? | BP-20 |

## What the code already gives us

- **One choke point for AI calls.** Four places call `model.reply(...)`: the portal assistant
  (`assistant/service.py`), the staff assistant (`staff_service.py`), grounded knowledge answers
  (`knowledge/answers.py`) and the public chat (`public_chat/service.py`). All get their model
  from `build_chat_model` / `chat_model_for`. A wrapper there can switch off, limit and meter
  every AI call without touching the four features. (BP-14, BP-09)
- **Token counts per answer** already come back (`ModelReply.usage`), and Prometheus counters for
  AI requests, tokens and cost exist - deliberately **without tenant labels** (privacy rule).
  (BP-09 adds a per-tenant table instead.)
- **Input and output guardrails** (`assistant/guardrails.py`: injection phrases, card and ID
  patterns, output clean-up) and the **approval queue** (ADR 0014) with a catalogue of three action
  kinds. (BP-21, BP-29)
- **Knowledge module:** chunks with citations, a similarity threshold (0.64) and a "not found"
  refusal, deterministic answer metrics, `knowledge/pii.py`. (BP-08)
- **CI** runs ruff, mypy, import-linter and pytest (with an RLS guard test); no dependency
  audit, secret scan or money-type check yet. (BP-20)

## The seven objects

### 1. BP-14 - Agent registry, budget caps, kill switch  (**ADR needed**)

- **What:** a table of the CRM's AI agents (`staff_assistant`, `portal_assistant`, `public_chat`,
  `knowledge_answers`, later more): owner, allowed tools, **monthly budget per organisation**,
  and an **on/off switch** checked before every AI call.
- **How (sketch):** `agents` module with an `agent_registry` table (forced RLS); a wrapper around
  `ChatModel` (governed model) that asks the registry first: off → "not available" (503 / polite
  text), over budget → refused; tool list intersected with the allowed tools. Admin page under
  Automation. A switch change is audited and notified.
- **Why an ADR:** a new module and table, a rule on every AI call, and a decision on what
  happens to a conversation in flight when an agent is switched off.
- **Steps (about 5):** AG0 ADR · AG1 module + table + registry service, tests first · AG2 the
  governed model wrapper on all four call sites · AG3 API + admin page · AG4 Playwright + docs + PR.
- **Questions for you:** budget in money or in tokens (money needs a price table)? What should
  the public website chat say when it is switched off?

### 2. BP-21 - Sentinel action verifier + prompt-injection firewall  (design note)

- **What:** a second, **rule-based** check on every AI-proposed action before it is stored in the
  approval queue, plus stronger input screening.
- **How (sketch):** a `sentinel` step inside `approvals.propose`: allowed fields per action kind,
  value ranges, tenant match, "the target record's own text contains instructions" detection,
  rate of proposals per asker. Input screening gains: hidden HTML, zero-width characters, external
  image links, very long repeated text. A failed check refuses the proposal with a stable code and
  is audited (never silently dropped).
- **Steps (about 4):** SN0 design · SN1 rules + tests first (including a library of attack
  strings) · SN2 hook into `propose` and the guardrails · SN3 evaluation cases in the BP-10
  harness + docs + PR.
- **Depends on:** BP-05 (done), BP-10 (attack cases are exactly what the harness is for).

### 3. BP-29 - Verification artifacts + ForcedLeak / BodySnatcher defences  (design note)

- **What:** each proposal stores a record: the state **before and after**, and the **rules that
  were checked** (BP-21's results). Text from public forms is cleaned (hidden HTML, zero-width
  characters, external image links) before it reaches any prompt; identity comes only from the
  verified token, never from tool arguments.
- **How (sketch):** a JSON `artifact` on the proposal (or a small linked table, decided in the
  design), shown on the approval card ("Would change: status new → contacted"), exposed at
  `GET /api/v1/approvals/actions/{id}/artifact`. Cleaning lives in one function used by the public
  chat, lead notes in prompts and e-mail text in prompts.
- **Steps (about 4):** VA0 design · VA1 cleaning function + tests · VA2 artifact on propose and
  approve (before/after from the owning module) · VA3 screens + docs + PR.
- **Depends on:** BP-05, BP-21.

### 4. BP-09 - AI usage and cost per organisation  (design note)

- **What:** an `ai_usage` table (tenant, feature, model, tokens in/out, cost as `Decimal`,
  latency) and a usage page for admins. Prometheus stays without tenant labels.
- **How (sketch):** the same governed-model wrapper from BP-14 writes one row per call (IDs and
  numbers only, never text); a price table in settings (one place, dated). Monthly totals feed
  BP-14's budget check.
- **Steps (about 4):** US0 design · US1 table + service, tests first · US2 hook into the wrapper
  + budgets · US3 usage page + docs + PR.
- **Depends on:** BP-14 (the wrapper). It is built second *because* BP-14's budgets need it - the
  two may share a step plan.

### 5. BP-08 - Cited RERA / brochure answers + "I don't know" gate  (design note)

- **What:** property brochures and RERA numbers live in the knowledge base; an answer must cite a
  source or refuse - for the public chat and staff, not just the portal.
- **How (sketch):** document types for brochure / RERA record in `knowledge`; the answer pipeline
  already refuses when no chunk passes the threshold or no valid citation is present - extend
  the same gate to property questions; a `GET /leads/{id}/property-matches` list ranked by the
  buyer's budget, type and location with a citation per match. Public chat gets *no* new tools
  (ADR 0013 stays: it can only save a lead) - any property answers there are a later, separate ADR.
- **Steps (about 5):** PM0 design · PM1 document types + ingestion · PM2 matching with citations,
  tests first · PM3 screens · PM4 evaluation cases (BP-10) + docs + PR.
- **Depends on:** the knowledge module, BP-10 (citation cases).

### 6. BP-15 - Live RERA / company web check  (**ADR needed**)

- **What:** an agent looks up a RERA number or company on public websites and stores the evidence.
- **Why an ADR:** it **sends data outside** (the number or company name), depends on site terms,
  needs **SSRF protection** (never fetch internal addresses), and a budget (BP-14).
- **Steps (about 6):** RV0 ADR · RV1 safe fetcher (allow-list, no private addresses, size/time
  limits), tests first · RV2 evidence storage · RV3 agent tool + approval for what it saves ·
  RV4 screens · RV5 docs + PR. Runs against a **local fake** until you say "go live" (ADR 0007).
- **Depends on:** BP-14, BP-05, BP-08.

### 7. BP-20 - CI security gate  (short note)

- **What:** new required CI jobs: dependency audit (`pip-audit`, `npm audit`), a secret scan, a
  "no `float` for money" check, and the existing RLS guard kept as is.
- **Steps (about 3):** SG0 short note · SG1 scripts + tests (a deliberate bad sample must fail)
  · SG2 CI jobs + docs + PR. Known risk: an audit can fail on a vulnerability nobody can fix yet;
  the note will say how an exception is recorded (named, dated, reviewed).
- **Depends on:** nothing - it could also run earlier if you want a safety net sooner.

## Dependencies at a glance

```
BP-05 (done) ─► BP-21 ─► BP-29
BP-10 ────────► BP-21 (attack cases)     BP-14 ─► BP-09 ─► (budgets back into BP-14)
BP-08 ─► BP-15 (also needs BP-14, BP-05)       BP-20 (independent)
```

## What would be decided with you, per object

Each object starts with its design note (and an ADR for BP-14 and BP-15) that you read and
approve before any code, exactly like BP-05 and BP-10. This roadmap is not an approval of any of
them.
