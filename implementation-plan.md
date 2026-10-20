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

## Phase 5 — Tenancy, authorization foundation & User/Role Management (Module 1)  *(roles, permissions, tenant + record-level policies, portal grants, audit log, user administration + onboarding (ADR 0004, docs/onboarding.md) done; RLS, teams, outbox pending)*

**Work:** `tenants`, `users`, `teams`, `roles`, `permissions` tables; `TenantScopedRepository`;
RLS policies + `SET LOCAL app.tenant_id`; `require_permission` dependency; policy framework;
audit log; outbox table + worker skeleton; admin UI to list users, assign roles and teams.

**Acceptance criteria**
- Tenant admin can manage users/roles/teams of **their** tenant only.
- RLS test: a raw query without `app.tenant_id` set returns no rows.
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

## Phase 16 — Marketing Management (Module 7)

**Acceptance criteria**
- Campaigns, segments (saved filters), email templates, sends via worker to Mailpit, consent/unsubscribe tracking.
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

## Phase 19 — External Integrations (Module 17)

**Acceptance criteria**
- Connector interface + first agreed connector(s); signed outgoing webhooks with retries; verified, idempotent incoming webhooks.
- Integration credentials encrypted at rest and never logged.
- Definition of Done checklist complete.

## Phase 20 — AI Chatbot & Voice Assistant (Module 16)  *(20a text chat in the portal done — see docs/assistant.md; 20b knowledge base (pgvector), 20c voice pending)*

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
