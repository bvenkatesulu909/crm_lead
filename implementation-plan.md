# crm-lead — Implementation Plan

We build one phase at a time. A phase is **done** only when all its acceptance criteria are met
**and** the listed tests have actually been run and passed. After each phase we stop, review, and
get approval before starting the next.

Architecture reference: [architecture.md](architecture.md). Project rules: [CLAUDE.md](CLAUDE.md).

## Definition of Done (applies to every phase that adds a business module)

- [ ] Alembic migration created, reviewed, and `upgrade head` + `downgrade -1` both work.
- [ ] Every tenant-owned table has `tenant_id`, RLS policy, and tenant-first indexes.
- [ ] Endpoints require authentication and declare their RBAC permission.
- [ ] Record-level policy implemented in `policies.py` and applied to reads, lists, updates, deletes.
- [ ] IDs received from the client are verified through scoped repositories (404 when not allowed).
- [ ] Tests: happy path, validation errors, **tenant isolation**, **role denial**, **record-level denial**, **ID tampering**.
- [ ] Audit log entries written for create/update/delete.
- [ ] import-linter boundaries pass; ruff, mypy, ESLint, `tsc` pass.
- [ ] Playwright test for the main user journey of the module.
- [ ] Short design note in `docs/modules/<module>.md`; new env vars added to `.env.example`.

---

> **Current plan (2026-10-18):** see [docs/gap-analysis.md](docs/gap-analysis.md) for the inventory and
> the proposed order of the remaining work: Phase A (baseline: first commit, status markers,
> import-linter) → B (accounts/contacts, Phase 6) → C (outbox, teams, RLS, MinIO) → D (pipeline,
> activities) → E (documents, products, quotes) → F (assistant completion) → G (marketing,
> automation, reports, integrations) → H (hardening).

> **Build order update (2026-10-18, ADR 0003):** after the frontend workflows, the owner chose
> to build the AI assistant's prerequisites first, in this order: **Phase 15 (customer portal UI)
> → Phase 14 (support tickets) → Phase 12 (orders) → Phase 13 (invoices) → Phase 20 (AI
> assistant: text chat first, then voice)**. Other phases follow afterwards.

## Phase 0 — Planning & repository bootstrap  *(done; first commit made in Phase A)*

**Work:** architecture.md, implementation-plan.md, CLAUDE.md, .gitignore, folder structure proposal.
Then (after approval): `git init`, README.md, `.editorconfig`, `.gitattributes`, `docs/adr/0001-modular-monolith.md`.

**Acceptance criteria**
- Documents reviewed and approved by the project owner.
- Git repository initialised with a first commit containing only documentation and config files.
- Tool versions verified on the machine: Git, Docker Desktop (engine running), Python 3.12 (via uv), uv, Node.js 22 LTS or newer LTS, npm.

## Phase 1 — Local infrastructure (Docker Compose)  *(PostgreSQL, Keycloak (on PostgreSQL), Mailpit done; MinIO pending)*

**Work:** `infrastructure/docker-compose.yml` with PostgreSQL 16, Keycloak, MinIO, Mailpit; `infrastructure/.env.example`;
named volumes; health checks; Postgres init script creating `crm` and `crm_test` databases and a
non-owner application role.

**Acceptance criteria**
- `docker compose up -d` starts all containers and they report healthy.
- Keycloak admin console, MinIO console and Mailpit UI open on localhost.
- Can connect to PostgreSQL as the app role; app role is **not** the table owner.
- No passwords in committed files (only in git-ignored `infrastructure/.env`).

## Phase 2a — Backend foundation  *(done)*

**Work:** `backend/` with `requirements.txt` / `requirements-dev.txt` (pinned), FastAPI app factory
(`app/main.py`), `core/config.py` (pydantic-settings, `CRM_` env prefix), JSON structured logging
with request IDs, Problem Details error responses, CORS explicit allowlist, `GET /api/v1/health`,
`.env.example`, pytest tests, ruff + mypy config.

**Acceptance criteria**
- API starts with `uvicorn app.main:app --reload`; OpenAPI docs at `/docs`.
- `GET /api/v1/health` returns 200 `{"status":"ok",...}` with an `X-Request-ID` header.
- CORS: configured origins allowed; unknown origins and `*` rejected (tested).
- 404 / 405 / 422 / 500 all return `application/problem+json`; 500 never leaks internals (tested).
- Invalid configuration stops the app at startup (tested).
- `pytest`, `ruff check`, `ruff format --check`, `mypy` all pass.

## Phase 2b — Database foundation  *(done)*

**Work:** `core/db.py` (SQLAlchemy engine/session, psycopg), Alembic setup, `GET /api/v1/health/ready`
(checks DB), pytest fixtures using the `crm_test` database, initial models and migration 0001
(`tenants`, `users`, `accounts`, `contacts`, `leads` with composite same-tenant foreign keys).
import-linter config moves to Phase 5, when modules get services.

**Acceptance criteria**
- `/api/v1/health/ready` returns 200 when DB is up and 503 when it is down.
- App refuses to start if the database URL is missing (tested).
- Migration 0001 applies, rolls back and re-applies; `alembic check` finds no model/migration drift.
- Database rejects cross-tenant references, duplicate per-tenant keys and invalid statuses (tested).
- API role cannot create, alter or drop tables (tested).
- All Phase 2a checks still pass.

## Phase 3 — Frontend skeleton  *(done with frontend workflow 1 — see docs/frontend.md)*

**Work:** `frontend/` Next.js (App Router, TypeScript, Tailwind, ESLint, Prettier), base layout,
`(staff)` and `(portal)` route groups, typed API client, Playwright setup.

**Acceptance criteria**
- `npm run dev` serves the app; `npm run build` succeeds; `npm run lint` and `tsc --noEmit` pass.
- Playwright smoke test (home page loads) passes.

## Phase 4 — Authentication (Keycloak OIDC)  *(done: backend token checks, Keycloak realm, Next.js login with PKCE and server-side session)*

**Work:** Keycloak realm `crm` (clients `crm-web`, `crm-api`, `crm-portal`, roles, token mappers
for `tenant_id` and `user_type`), exported to `infrastructure/keycloak/realm-crm.json`; OIDC login in Next.js (openid-client + jose)
(Authorization Code + PKCE, tokens server-side, refresh, logout); FastAPI JWT verification against
JWKS producing a `Principal`; `/api/v1/me` endpoint.

**Acceptance criteria**
- A staff user can log in and out through Keycloak in the browser; tokens never reach browser JS.
- API rejects: no token, expired token, wrong issuer, wrong audience, bad signature, `alg=none` (tests).
- `/api/v1/me` returns the user, tenant and roles from the token.
- Playwright: login → see name → logout.

## Phase 5 — Tenancy, authorization foundation & User/Role Management (Module 1)  *(roles, permissions, tenant + record-level policies, portal grants, audit log, user administration + onboarding (ADR 0004, docs/onboarding.md), outbox (ADR 0005) and RLS on every tenant table (ADR 0009, 2026-10-23, docs/rls-audit.md) done; teams pending)*

**Work:** `tenants`, `users`, `teams`, `roles`, `permissions` tables; `TenantScopedRepository`;
RLS policies + `SET LOCAL app.tenant_id`; `require_permission` dependency; policy framework;
audit log; outbox table + worker skeleton; admin UI to list users, assign roles and teams.

**Acceptance criteria**
- Tenant admin can manage users/roles/teams of **their** tenant only.
- RLS test: a raw query without `app.tenant_id` set returns no rows. *(done: `tests/db/test_rls_tenant_tables.py`, every tenant table)*
- Cross-tenant tests return 404; missing permission returns 403.
- Audit entries recorded for role changes.
- Worker processes a test outbox event and retries on failure.

## Phase 6 — Customer Accounts & Contacts (Modules 2, 3)  *(done 2026-10-19 as gap-analysis Phase B — see docs/accounts-contacts.md; teams still open (Phase C))*

**Acceptance criteria**
- CRUD, search and pagination for accounts and contacts; contact ↔ account linking.
- Creating a contact on an account the user cannot access → 404.
- Sales rep sees only own/shared/team records according to policy; manager sees team records.
- Definition of Done checklist complete.

## Phase 7 — Lead Management (Module 4)  *(done — see docs/leads.md; duplicate detection deferred; UI for logging activities missing)*

**Acceptance criteria**
- Lead capture, assignment, status pipeline, duplicate detection (same email within tenant).
- Lead conversion creates account + contact + (optional) opportunity in one transaction and emits `lead.converted`.
- Definition of Done checklist complete.

## Phase 8 — Sales Opportunity Management (Module 5)  *(done 2026-10-19 as gap-analysis Phase D — see docs/pipeline-activities.md; stages fixed per tenant for now, forecast = weighted value; quote links come with Phase 11)*

**Acceptance criteria**
- Configurable pipelines and stages per tenant; opportunities linked to accounts/contacts; amount as NUMERIC + currency.
- Kanban board UI; stage history recorded; forecast totals per owner/team respect record-level rules.
- Definition of Done checklist complete.

## Phase 9 — Activity & Task Management (Module 6)  *(done 2026-10-19 as gap-analysis Phase D; reminders in the CRM (bell, overdue, calendar); e-mail reminders wait for the Phase C worker)*

**Acceptance criteria**
- Tasks, calls, meetings, notes linkable to any allowed record; due dates and reminders (via worker, email to Mailpit).
- Activity timeline on account/contact/lead/opportunity shows only activities the user may see.
- Definition of Done checklist complete.

## Phase 10 — Document Management (Module 15)  *(done 2026-10-19 — see docs/documents.md: uploads with versions on accounts and deals, portal sharing, type/size checks, quote PDFs; virus scanning and documents on other records still open)*

**Acceptance criteria**
- Upload/download/version documents stored in MinIO, metadata in PostgreSQL, linked to records.
- File type/size limits enforced; download requires authorization on the linked record.
- Cross-tenant object keys are impossible (tested).
- Definition of Done checklist complete.

## Phase 11 — Product & Quotation Management (Module 8)  *(done 2026-10-19 as gap-analysis Phase E1 — see docs/quotes-catalog.md; approval above 10 % discount, revisions, portal accept/decline, quote → order; printable page instead of a stored PDF until MinIO exists)*

**Acceptance criteria**
- Products, price books, quotes with lines, discounts and taxes; totals computed server-side.
- Quote PDF generated and stored as a document; quote status workflow (draft → sent → accepted/rejected).
- Definition of Done checklist complete.

## Phase 12 — Order Management (Module 9)  *(done — see docs/orders.md; built before Phase 11, so orders are created directly by staff for now; quote → order conversion comes with Phase 11)*

**Acceptance criteria**
- Accepted quote converts to an order; order lines are a snapshot of quote lines.
- Order status lifecycle; cancellation rules enforced server-side.
- Definition of Done checklist complete.

## Phase 13 — Invoice & Payment Management (Module 10)  *(done — see docs/invoices.md; invoices from orders, gapless numbers at issue, DB-frozen issued invoices, credit notes, manual payments with reversals)*

**Acceptance criteria**
- Invoices from orders, sequential invoice numbers per tenant, payments (manual entry first), balances, credit notes.
- Invoices are immutable once issued (corrections only via credit notes).
- No real payment provider yet; no card data stored.
- Definition of Done checklist complete.

## Phase 14 — Customer Support Management (Module 11)  *(done — see docs/support.md; knowledge base moves to the assistant phase)*

**Acceptance criteria**
- Tickets with priority, status, SLA timers (worker), assignment, internal vs. public comments, knowledge base articles.
- Definition of Done checklist complete.

## Phase 15 — Customer Portal (Module 12)  *(done for accounts, orders, invoices, tickets and the assistant; quotes and documents follow Phases 11 and 10)*

**Acceptance criteria**
- Portal login with `user_type=customer`; portal users linked to accounts via `portal_access_grants`.
- Portal users see only their granted accounts' quotes, orders, invoices, tickets and public documents.
- Tests: portal user changing an `account_id`/record ID in a request → 404; staff token on portal API and portal token on staff API → rejected.
- Internal fields (notes, margins, internal comments) never appear in portal responses (tested).
- Playwright: two portal users from different accounts cannot see each other's data.

## Phase CC — Communication Center (Module 18)  *(ADR 0012, accepted by the owner 2026-10-24; CC0–CC4 done 2026-10-24, CC5 and CC6 done 2026-10-25 - phase complete, see docs/communications.md; merged into main 2026-10-25 as PR #15)*

One-to-one e-mail from the CRM: a composer, templates and each record's conversation history.
Built before Marketing (Phase 16), which will reuse its templates. Receiving replies
automatically waits for Phase 19 (Integrations); until then received e-mails are logged by hand.

**Steps (each stops for review)**
- **CC0** — ADR 0012 and this phase description (documents only).
- **CC1** — `communications` module skeleton; tables `email_templates` and `email_messages`
  (migration 0038, ENABLE + FORCE RLS + tenant policy); permissions `communication:send`,
  `communication:read:all`, `communication:read:own`, `communication:template:manage`.
- **CC2** — Sending: `POST /api/v1/communications/emails` → `communication.email` outbox job →
  worker sends (queued → sent / failed, retries when the mail server is down); recipient is a
  lead or contact loaded through its module's `api.py`, address taken from the record;
  Reply-To is the sender; timeline entry of kind `email`; audit; withdrawn consent refused;
  200 e-mails per user per hour; `communication.email_failed` event → notification.
- **CC3** — Templates: create, edit, deactivate, preview; placeholders from a fixed list, unknown
  ones refused; plain text only.
- **CC4** — Conversation history per lead, contact, account and deal; "log a received e-mail".
- **CC5** — Screens: "Send e-mail" dialog on lead, contact, account and deal pages; Templates
  page; Communication Center page (filters); module tile "Available"; Vitest tests.
- **CC6** — Playwright journey that finds the e-mail in Mailpit; `docs/communications.md`;
  CLAUDE.md status; full test run (backend, Vitest, E2E, production build).

**Acceptance criteria**
- Staff can e-mail only leads and contacts they may read; another tenant's or another agent's
  record ID → 404 (tested). The client never supplies the address.
- E-mails are sent only by the worker; a mail server outage is retried and visible as a status.
- A contact with withdrawn consent can't be e-mailed (tested).
- Templates can't run code; unknown placeholders are refused (tested).
- The Communication Center list is filtered in SQL (`read:all` vs `read:own`); a record's history
  follows that record's read rules.
- E-mail bodies never appear in logs or event payloads.
- Definition of Done checklist complete.

## Phase PC — Public website chat that saves real-estate leads (BP-01, Module 20)  *(ADR 0013 accepted 2026-10-25; PC0–PC6 done; merged into `main` as PR #17)*

A chat on the company's public website: a home buyer gives name, phone, property type, budget
and location, and a lead is saved for the sales team. Tickets CRM-104, CRM-105, CRM-106a/b.
The first endpoint where someone without an account creates data - see ADR 0013 for the
protection (server-only key, one tenant per website, limits, guardrails, plain-text answers).

**Steps (each stops for review)**
- **PC0** — ADR 0013 and this phase description (documents only).
- **PC1 (CRM-104)** — DeepSeek tool calling in `DeepSeekChatModel`: tools in OpenAI format,
  `tool_calls` → `ToolUse`, tool results as `role: "tool"`; Anthropic unchanged; tests with a
  fake HTTP client (no key needed).
- **PC2 (CRM-105)** — Real-estate lead fields `property_type`, `budget_min_inr`,
  `budget_max_inr`, `location` (migration 0040, database checks, schemas, lead form and page).
- **PC3 (CRM-106a)** — `public_chat` module: `public_chat_sessions` + `public_chat_messages`
  (migration 0041, forced RLS), settings (tenant slug, server key, provider, limits),
  `POST /api/v1/public/chat` with the server key, hashed conversation token, `save_lead` tool
  (lead via `leads/api.py` as the Automation identity, one per conversation), guardrails,
  limits, `fake` provider refused in production.
- **PC4 (CRM-106a)** — `public_chat.lead_captured` event → notification to sales managers;
  transcript on the lead page for staff who may read the lead; 30-day clean-up of
  conversations without a lead (worker).
- **PC5 (CRM-106b)** — Web: public `/chat` page (plain-text answers, privacy notice, honeypot)
  and `/api/public-chat` route handler (adds the server key, visitor address and httpOnly
  `crm_chat` cookie); `proxy.ts` exception; Vitest.
- **PC6** — Playwright journey with the fake provider, `docs/public-chat.md`, refreshed
  inventory, full run, PR.

**Acceptance criteria**
- Without the server key, with the feature switched off, or for an unknown conversation token:
  404 (tested). The tenant comes only from the server setting.
- A visitor can continue only their own conversation and can never read CRM data (tested).
- One lead per conversation, in the configured tenant only, with the real-estate fields; the
  database refuses impossible budgets (tested).
- Every limit and guardrail refusal is tested; answers are shown as plain text.
- Works without any paid key (fake provider); the fake provider can't start in production.
- Going live is not part of this phase (ADR 0007, owner's "go live").
- Definition of Done checklist complete.

## Phase AP — Approval queue for AI-proposed actions (BP-05, Module 21)  *(ADR 0014 accepted 2026-10-25; AP0–AP5 done; merged into `main` as PR #18)*

The AI may **suggest** changes to real records (lead status, assignment, follow-up task); a
sales manager or tenant admin approves or rejects; an approved change runs through the owning
module's `api.py` as the approver, in one locked transaction, with audit. No self-approval.
First object of the rest of AI Track A1 (then BP-10 evaluation harness, BP-11 MCP server).

**Steps (each stops for review)**
- **AP0** — ADR 0014 and this phase description (documents only).
- **AP1** — `approvals` module: `agent_actions` (migration 0042, forced RLS), permissions
  `agent_action:propose` / `agent_action:approve`, catalogue `lead.set_status`, `lead.assign`,
  `activity.create_task`, propose / approve / reject with row lock, version check, no
  self-approval, failure rollback to a savepoint, audit; `leads_api.assign_lead`.
- **AP2** — API endpoints; events `agent_action.proposed` / `agent_action.decided` →
  notifications; worker expiry after 7 days; at most 20 pending proposals per requester.
- **AP3** — Staff assistant: tools passed to the model; `propose_lead_status`,
  `propose_lead_assignment`, `propose_follow_up_task`; scripted fake-model tests.
- **AP4** — Web: Approvals page (pending cards, history, my proposals), record links,
  Automation card, the assistant shows the waiting proposal; Vitest.
- **AP5** — Playwright journey, `docs/approvals.md`, refreshed inventory, full run, PR.

**Acceptance criteria**
- The model can only create **pending** proposals of catalogue kinds; nothing changes before a
  person approves (tested).
- The requester can never approve their own proposal, admins included (tested).
- An approved action runs with the approver's rights and record rules; a target the approver
  can't see is 404 and changes nothing (tested).
- Double decisions (409), expiry, failure rollback, the pending limit, tenant isolation, role
  denial and ID tampering are tested.
- Works without any paid key (fake model in tests). Definition of Done checklist complete.

## Phase EV — Agent evaluation harness (BP-10)  *(design note accepted 2026-10-25; EV0-EV5 done; the one paid DeepSeek pass run 2026-10-26)*

Fixed test conversations that measure what the CRM's AI agents DO - which tool they pick, with
which arguments, which tools they must never touch - and a cited-answer set that runs without a
paid key. Same expectations are played with a scripted model in CI (tests the CRM around the
model) and, on demand, with a real model (tests the model's behaviour). Design note:
`docs/agent-evals.md` (not an ADR: no new data flow, table or security rule).

**Steps (each stops for review)**
- **EV0** - design note and this description (documents only).
- **EV1** - case format (`backend/evals/agents/*.json`), loader, argument matchers, scoring,
  dataset hash; pure unit tests first.
- **EV2** - runner for the staff assistant against the real test database with a scripted model;
  about 12 cases; a pytest file that runs them in CI.
- **EV3** - portal assistant, public chat and guardrail cases (about 18 more).
- **EV4** - cited-answer cases in CI without a paid key (fake embedder, scripted answers, existing
  metrics), plus "not found" cases.
- **EV5** - CLI `python -m scripts.eval_agents --provider fake|deepseek|anthropic`, scorecard JSON,
  `--baseline`, CI job-summary table, final docs, full runs, pull request.

**Acceptance criteria**
- Every case passes with the scripted model in CI; any failing case fails the pull request.
- Forbidden-tool violations and "claimed done" answers are 0.
- No secrets, no real data, no paid call in CI; real-model results are a report, never a gate.
- Definition of Done checklist complete.

## Phase AG — Agent registry, budgets and kill switch (BP-14)  *(ADR 0016 accepted 2026-10-26; AG0-AG4 done; Phase AG complete)*

A list of the CRM's AI agents with an owner, allowed tools, a monthly token budget per
organisation and an on/off switch, enforced by one governed-model wrapper at the four places that
call a language model. Design: `docs/adr/0016-agent-registry-budgets-kill-switch.md`.

**Steps (each stops for review)**
- **AG0** - ADR 0016 and this description (documents only).
- **AG1** - module `agents`: catalogue, `agent_settings` + `agent_usage` (forced RLS, migration
  0043), services, permissions `agent:read` / `agent:manage`; tests first.
- **AG2** - governed model on the four call sites; evaluation cases in the BP-10 harness.
- **AG3** - API `/api/v1/agents`, audit, 80 % notification, switch events.
- **AG4** - admin page, Playwright, docs, full runs, pull request.

**Acceptance criteria**
- An agent that is off or over budget never reaches the model (proven with a model that fails if called).
- A tenant admin can switch, cap and narrow an agent; other organisations are unaffected; changes are audited.
- Definition of Done checklist complete.

## Phase SN — Sentinel action verifier and input screening (BP-21)  *(ADR 0017 accepted 2026-10-26; SN0-SN4 done; Phase SN complete)*

A deterministic second check on every AI proposal before it reaches the approval queue (words,
pattern, state, tenant, the record's own text), plus stronger input screening. Design:
`docs/adr/0017-sentinel-action-verifier.md`.

**Steps (each stops for review)**
- **SN0** - ADR 0017 and this description (documents only).
- **SN1** - `core/screening.py`, `approvals/sentinel.py`, an attack-string library; tests first.
- **SN2** - hook into `propose()` / `approve()`, migration 0044 (`verification`), audit, metric.
- **SN3** - input screening in the guardrails and the staff prompt; warnings on the approval card.
- **SN4** - BP-10 cases, docs, full runs, pull request.

## Phase VA — Verification artifacts and injection defences (BP-29)  *(ADR 0018 accepted 2026-10-27; VA0-VA4 done, phase complete)*

Every AI proposal stores the plan (what will change, before and after), is checked after it runs
(did it match the plan?), and outside text that could carry an injection is cleaned at the door and
at the exit; identity comes only from the token, proven by a test. Design:
`docs/adr/0018-verification-artifacts-and-injection-defences.md`.

**Steps (each stops for review)**
- **VA0** - ADR 0018 and this description (documents only).
- **VA1** - `spec` per action kind, artifact v2 at `propose()`, `outcome` at `approve()`.
- **VA2** - door and exit: screening of stored chat text, link/image removal in answers, the
  identity-argument test, the no-fetch test.
- **VA3** - API, approval card ("Would change", "What happened"), CSP in report-only mode.
- **VA4** - BP-10 cases, `docs/injection-defences.md`, full runs, pull request.


## Phase QA — Qualifier, the lead qualification agent (BP-03)  *(design note proposed 2026-10-30; QA0 done)*

Design: [docs/qualifier.md](docs/qualifier.md). Waits for the owner's answers to its six questions. No code before the design is accepted.

| Step | Content |
|---|---|
| QA0 | Design note + this plan (documents only) |
| QA1 | Qualification procedures: migration, service, admin API, permissions |
| QA2 | The assessment: `submit_assessment`, validation, mapping to proposals, `lead_assessments`; scripted model |
| QA3 | Registry entry, limits, audit, metrics, optional automatic run in the worker |
| QA4 | Screens: lead card with the Qualify button, admin page with a dry run, notifications |
| QA5 | BP-10 evaluation cases, final docs, Playwright journey, full runs |

## Phase WC — Live web check of a RERA number or a company (BP-15)  *(ADR 0019 accepted 2026-10-30; WC0, WC1, WC2a, WC2b, WC2c, WC4 done)*

Accepted 2026-10-30 with the recommended answers to the five questions in ADR 0019.

| Step | Content |
|---|---|
| WC0 | ADR 0019 + this plan (documents only) |
| WC1 | `app/core/webfetch.py`: hardened fetcher (https only, public addresses only, same host, size/time limits, robots, rate limits), tested without a network |
| WC2a | Pure part of `webcheck`: query rules, demo source catalogue, deterministic parsers, in-process demo registry (no database) |
| WC2b | `webcheck` store: migration 0045 (`web_evidence`, forced RLS, insert-only), permissions, settings, service (request, run, list, retention), worker job, audit |
| WC2c | `webcheck` API: `POST /webcheck/checks`, `GET /webcheck/evidence`, schemas, OpenAPI, inventory |
| WC3 | Agent registry entry (no model), staff assistant tool `check_rera`, limits |
| WC4 | Screens: Check button and Evidence card on lead and account pages |
| WC5 | BP-10 cases, `docs/webcheck.md`, Playwright journey, full runs |
## Phase 16 — Marketing Management (Module 7)

**Acceptance criteria**
- Campaigns, segments (saved filters), sends via worker to Mailpit, consent/unsubscribe tracking.
- E-mail templates come from the Communication Center (`communications/api.py`, ADR 0012), not a
  second template system; bulk sending requires `email_consent = granted`.
- Unsubscribed contacts are never emailed (tested).
- Definition of Done checklist complete.

## Phase 17 — Workflow Automation (Module 14)  *(ADR 0006. done 2026-10-19 — 17a domain events, notifications, reminder e-mails; 17b automation rules with run log and loop limits; see docs/workflows.md; webhooks moved to Phase 19)*

**Acceptance criteria**
- Tenant admins define rules: trigger (event or schedule) → conditions → actions (create task, send email, update field, webhook).
- Rules run in the worker, are logged per run, cannot loop infinitely (depth/limit), and cannot exceed tenant scope.
- Definition of Done checklist complete.

## Phase 18 — Reports & Analytics (Module 13)  *(done 2026-10-19: role dashboards (part 1) + standard reports, report builder and CSV export (part 2) - see docs/reports.md and docs/dashboard.md)*

**Acceptance criteria**
- Standard dashboards (pipeline, win rate, revenue, ticket SLA) and a simple report builder.
  - **Done (2026-10-19, part 1):** role dashboards on `/` (executive, sales manager, sales rep);
    leads, customers, pipeline, follow-ups, activity feed, team table, revenue, orders and support;
    period and sales rep filters; see [docs/dashboard.md](docs/dashboard.md).
  - **Done (2026-10-19, part 2):** win rate, lead conversion, revenue & quotes and support SLA
    reports; report builder; CSV export with audit and CSV-injection protection; see
    [docs/reports.md](docs/reports.md).
  - **Still open:** saved/scheduled reports, charts, forecast, and the "team" filter (after teams).
- All report queries apply tenant + record-level filters; CSV export respects the same rules (tested).
- Definition of Done checklist complete.

## Phase 19 — External Integrations (Module 17)  *(CRM MCP server: ADR 0015, steps MCP0-MCP6; MCP1 done 2026-10-26)*

**Acceptance criteria**
- Connector interface + first agreed connector(s); signed outgoing webhooks with retries; verified, idempotent incoming webhooks.
- Integration credentials encrypted at rest and never logged.
- Definition of Done checklist complete.

## Phase 20 — AI Chatbot & Voice Assistant (Module 16)  *(20a text chat in the portal done — see docs/assistant.md; 20b knowledge base (pgvector) designed in docs/rag-knowledge-base.md + proposed ADR 0010, not built; 20c voice pending)*

**Acceptance criteria**
- Chat UI in staff app; assistant answers questions and performs actions only via permission-checked tools acting as the current user.
- Write actions require explicit user confirmation.
- Tests: assistant cannot read another tenant's or unauthorized record even if asked to; prompt-injection text inside a record does not trigger actions.
- Voice input/output works in a supported browser.
- Provider API key from env var only.

## Phase 21 — Hardening & release readiness (local)

**Acceptance criteria**
- Security review (OWASP ASVS checklist level 2 scope), dependency vulnerability scan (`pip-audit`, `npm audit`).
- Backup/restore script for PostgreSQL and MinIO tested locally.
- Performance check with seeded data (e.g. 100k leads) — key list endpoints under agreed latency.
- Full pytest + Playwright suites pass; README covers setup from a clean Windows machine.
