# CLAUDE.md — crm-lead project instructions

This file is read by Claude Code at the start of every session. It also serves as the contributor guide.

## Project

**crm-lead** is a production-oriented CRM built as a **modular monolith**, running locally on Windows
with Docker Desktop. Read [architecture.md](architecture.md) for the design and
[implementation-plan.md](implementation-plan.md) for the phases. The project owner is learning,
so explanations matter as much as code.

Stack: Next.js 16 + React 19 + TypeScript + Tailwind 4 (`frontend/`) · Python 3.12 + FastAPI + SQLAlchemy 2 +
Alembic (`backend/`) · PostgreSQL · Keycloak (OIDC) · SeaweedFS (S3 files) · Mailpit · pytest · Playwright.

## Working rules (must follow)

1. **One phase at a time.** Only work on the current phase in `implementation-plan.md`. Stop at the end of a phase and wait for approval.
2. **Never generate the whole CRM in one step.** Small, reviewable changes.
3. **Explain every step in beginner-friendly language**: what a file is for, why a library is needed, what a command does.
4. **Ask before** destructive commands (deleting files/volumes/databases, `docker compose down -v`, `git reset --hard`, force-push, dropping tables, rewriting migrations already applied) and before **major architectural changes** (anything marked [ADR] in architecture.md).
5. **Never claim tests passed unless they were actually run** in this session and the output showed success. If tests were not run, say so.
6. **Cloud deployment only as described in ADR 0007** (Netlify for the web app, separate hosts for the rest) and only after its hardening checklist - never with development settings, test users or development passwords. Until the owner says "go live", everything runs locally.
7. **Commands for the user use Windows CMD syntax** (e.g. `copy`, `set`, `^` for line continuation, `.venv\Scripts\activate`). Do not give PowerShell- or bash-only commands to the user.
8. Keep `architecture.md`, `implementation-plan.md` and this file up to date when decisions change.

## Security rules (non-negotiable)

- **Tenant isolation:** every tenant-owned table has `tenant_id`; every query goes through a tenant-scoped repository; PostgreSQL RLS is enabled (ENABLE + FORCE + tenant policy on every new tenant table, in its migration - `test_rls_tenant_tables.py` enforces it). Tests create setup data as `crm_owner` (`committed_world`) and assert as `crm_app`; never weaken a policy to make a test pass. `tenant_id` comes **only** from the verified token.
- **Identity:** use `get_principal` / `require_any_permission` from `app.modules.identity.api` on every non-public endpoint; never write custom password storage (Keycloak owns credentials). See `docs/auth.md`.
- **Never trust client-supplied IDs** (account, contact, customer, owner, tenant…). Load them through the scoped repository + policy; return **404** if missing or not allowed.
- **Authorization on every endpoint:** RBAC permission (`require_permission("x:y")`) **and** record-level policy. Lists are filtered in SQL, not after loading.
- **Portal users** only see records of customer accounts in their `portal_access_grants`. Staff and portal APIs reject each other's tokens.
- **No secrets in code**, tests, fixtures, docs or Keycloak exports. Use environment variables; document them in `.env.example` with placeholders.
- Server-controlled fields (`tenant_id`, `created_by`, totals, invoice numbers, statuses with rules) are never accepted from the client — use separate input schemas.
- No raw string-built SQL. No logging of tokens, passwords, secrets or full personal data.
- Money uses `Decimal` / `NUMERIC`, never `float`.

## Architecture rules

- Backend modules live in `backend/app/modules/<module>/` with `router.py`, `schemas.py`, `models.py`, `repository.py`, `service.py`, `policies.py`, `api.py` (plus `rules.py` for pure business rules). Permission names are defined centrally in `app/core/auth/rbac.py`.
- A module may import only `app.core` and **other modules' `api.py`**. Enforced by import-linter (`lint-imports` in `backend`, contracts in `pyproject.toml`); `app.core` never imports modules.
- Cross-module side effects must not write into another module's tables: call that module's `api.py` in the same transaction, or publish a **domain event** (`app/core/events.py`, ADR 0006) in the same transaction for reactions that may happen later in the worker (notifications, workflow rules). Event payloads hold IDs and codes only; subscribers must be safe to run twice.
- Routers stay thin: validation in schemas, rules in services, queries in repositories.
- Every schema change = a new Alembic migration (never edit an applied migration; never change tables manually).
- Every write endpoint: service does the work without committing; the router commits once. Sensitive changes call `record_audit()` in the same transaction.
- Business errors raise `DomainError` subclasses (`app.core.errors`) with a stable `code`; never return ad-hoc error bodies.
- Frontend (`frontend/`, see `docs/frontend.md`): data loading in Server Components via `apiFetch` (`src/lib/server/api.ts`), changes via Server Actions. The browser never receives tokens (encrypted httpOnly `crm_session` cookie; never `localStorage`). UI permission checks (`src/lib/permissions.ts`) are for display only — the API decides.
- This Next.js version (16) differs from older docs: read `frontend/node_modules/next/dist/docs/` before using a Next.js API (e.g. `proxy.ts` replaces middleware).

## Testing rules

- Every module must include tests for: happy path, validation, **tenant isolation**, **role denial**, **record-level denial**, **ID tampering**.
- Backend tests run against a real PostgreSQL test database (`crm_test`), not SQLite.
- Each user-facing module gets at least one Playwright journey.
- Bug fixes start with a failing test that reproduces the bug.

## Code style

- Python: type hints everywhere; `ruff` for lint/format; `mypy` strict on `app/`. Use SQLAlchemy 2.0 style (`select()`, `Mapped[]`).
- TypeScript: `strict` mode; ESLint + Prettier; no `any` without a comment explaining why.
- Names: snake_case tables/columns (plural table names), UUID primary keys, `created_at`/`updated_at` in UTC.
- Comments explain *why*, not *what*.

## Commands (fill in as phases are completed)

> Run from Windows CMD. Paths are relative to the project root `E:\crm-lead`.

| Task | Command | Available from |
|---|---|---|
| Start infrastructure | `cd infrastructure && docker compose up -d` | Phase 1 |
| Infrastructure status | `cd infrastructure && docker compose ps` | Phase 1 |
| Stop infrastructure (keeps data) | `cd infrastructure && docker compose down` | Phase 1 |
| Create API virtual environment (once) | `cd backend && uv venv --python 3.12 .venv` | Phase 2a |
| Activate it (each new CMD window) | `cd backend && .venv\Scripts\activate` | Phase 2a |
| Install API dependencies | `uv pip install -r requirements-dev.txt` (venv active) | Phase 2a |
| Run API | `uvicorn app.main:create_app --factory --reload` (in `backend`, venv active) | Phase 2a |
| API tests | `pytest` (in `backend`, venv active) | Phase 2a |
| API lint / format / types | `ruff check . && ruff format --check . && mypy app tests` | Phase 2a |
| Module boundaries | `lint-imports` (in `backend`, venv active) | Phase A |
| Apply migrations | `alembic upgrade head` (in `backend`, venv active) | Phase 2b |
| Create migration | `alembic revision --autogenerate -m "message"` | Phase 2b |
| Export API contract (after endpoint/schema changes) | `python -m scripts.export_openapi` (in `backend`, venv active) | Phase 7 |
| Regenerate the project inventory (`docs/inventory.md`) | `python -m scripts.report_inventory` (in `backend`, venv active) | 2026-10-20 |
| Seed local test data (fictional) | `python -m scripts.seed_dev_data` (in `backend`, venv active) | Phase 4 |
| Seed fictional knowledge documents (RAG R1.6) | `python -m scripts.seed_knowledge_demo` (in `backend`, venv active) | RAG R1 |
| Keycloak admin console | http://localhost:9080/admin (credentials in `infrastructure\.env`) | Phase 4 |
| Local e-mail inbox (Mailpit) | http://localhost:8025 — invitations, verification, password reset | ADR 0004 |
| Run background worker (own CMD window) | `python -m app.worker` (in `backend`, venv active); `--once` runs due jobs and exits | ADR 0005 |
| File store (SeaweedFS, S3 API) | `127.0.0.1:9333`, keys in `infrastructure\.env`; started by `docker compose up -d` | ADR 0005 |
| Open the CRM to other devices on your network (see docs/network-access.md) | `python -m scripts.network_mode on <PC address>` / `off` / `status` (in `backend`, venv active), then `cd frontend && npm run dev:network` | Network mode |
| Install web dependencies | `cd frontend && npm install` | Phase 3 |
| Run web | `cd frontend && npm run dev` (http://localhost:3000) | Phase 3 |
| Web lint / types | `cd frontend && npm run lint && npm run typecheck` | Phase 3 |
| Web component tests | `cd frontend && npm test` | Phase 3 |
| E2E tests (needs Docker services) | `cd frontend && npm run test:e2e` | Phase 3 |
| Production build | `cd frontend && npm run build` — stop `npm run dev` first (or restart it afterwards): building while the dev server runs can leave it serving stale modules | Phase 3 |

## Current status

Full inventory and the plan for the remaining work: [docs/gap-analysis.md](docs/gap-analysis.md).

- **Done:**
  - Infrastructure: PostgreSQL, Keycloak (stores data in PostgreSQL), Mailpit, SeaweedFS file store (ADR 0005).
  - Backend foundation, database (migrations 0001–0009), and auth (Keycloak OIDC, RBAC,
    tenant + record-level policies).
  - Lead Management.
  - Frontend: login, dashboard, leads, accounts (read), orders, invoices, tickets, Users,
    Organisations, profile.
  - Customer portal: accounts, orders, invoices, tickets, assistant.
  - User onboarding (ADR 0004).
  - AI assistant text chat (Phase 20a).
- **Last full test run (2026-10-18):**
  - backend: 571 pytest passed (+4 live Claude evaluations, opt-in), import-linter 2 contracts kept;
  - frontend: 127 component tests passed;
  - end to end: 40 Playwright tests passed (+2 skipped: slow refresh, live assistant chat);
  - lint, types and production build all clean.
- **Dashboards (Phase 18, part 1)** — done 2026-10-19, not committed. See `docs/dashboard.md`.
  - `GET /api/v1/dashboard`: executive, manager and rep views; period and sales rep filters; figures from each module's `metrics.py` under its own policy.
  - Web: role dashboards on `/`.
  - Tests: backend 597 passed (incl. 26 dashboard tests), Vitest 142, E2E `dashboard.spec.ts` (4).
- **Phase B (accounts and contacts)** — done 2026-10-19, not committed. See `docs/accounts-contacts.md`.
  - Account CRUD, hierarchy, segment, deactivate/archive/restore, timeline; contacts module (CRUD, primary contact, consent, history); read-only `GET /opportunities`; lead activity logging UI; migration 0010.
  - Tests (run 2026-10-19): backend 651 passed (+4 opt-in skipped); Vitest 162 passed; full E2E 44 passed, then the 4 tests that expected the old screens were updated and pass; the only other failure is the live assistant test (Anthropic still answers 400).
- **Phase D (pipeline, activities and tasks)** — done 2026-10-19, not committed. See `docs/pipeline-activities.md`.
  - Opportunities: create/edit, Kanban board (drag & drop + "Move to"), won/lost/reopen, stage history.
  - Activities: tasks, follow-ups and logs on leads/accounts/contacts/deals; Tasks page, calendar, reminders bell; migration 0011.
  - E-mail reminders wait for the Phase C worker.
- **Phase B2 (customer relationship depth)** — done 2026-10-19, not committed. See `docs/customer-relationships.md`.
  - Segmentation fields + filters (incl. customer value), duplicate detection, ownership transfer (with contacts/open deals/open tasks), customer health + at-risk list, lead scoring, ticket category + satisfaction rating; migration 0012; new `relationships` module (no tables).
  - Backend 735 tests passed (full run 2026-10-19).
- **Phase E1 (products, price books, quotes)** — done 2026-10-19, not committed. See `docs/quotes-catalog.md`.
  - Catalogue and price books (managers maintain, everyone in sales/support reads); quotes priced from the price book, discount > 10 % needs a manager's approval (four-eyes), revisions, expiry, printable page; portal accept/decline; accepted quote → draft order; quote cards on account/deal pages and "From quote" on orders; migration 0013.
  - Tests (run 2026-10-19): backend 777 passed (+4 opt-in skipped), import-linter 2 contracts kept, ruff/mypy clean; Vitest 200 passed; full E2E 60 passed, 1 skipped, 1 failed (the live assistant test - Anthropic billing, known). Production build not re-run this phase.
- **Phase C1 (file store, mail, outbox + worker; ADR 0005)** — done 2026-10-19, not committed. See `docs/background-jobs.md`.
  - SeaweedFS container (S3 API; MinIO images are no longer published), `app/core/storage.py`, `app/core/mail.py` (SMTP → Mailpit on 127.0.0.1:2525), `outbox_jobs` table (migration 0014), worker `python -m app.worker` with retries and dead jobs.
  - Tests (run 2026-10-19): backend 810 passed (+4 opt-in skipped); ruff, mypy, import-linter clean; live smoke test against SeaweedFS, Mailpit and the worker passed. No module uses the worker yet (next: E2a quote PDFs, E2b e-mail quotes).
- **Step E2a (documents + stored quote PDFs; ADR 0005)** — done 2026-10-19, not committed.
  - `documents` module (migration 0015, rows can't be updated), quote PDF with ReportLab, `quote.pdf` job on send, `GET /quotes/{id}/pdf` and `/portal/quotes/{id}/pdf`, "Download PDF" buttons via Next.js route handlers (no token in the browser).
  - Tests (run 2026-10-19): backend 828 passed (+4 opt-in skipped), ruff/mypy/import-linter clean; Vitest 202 passed; full E2E 60 passed, 1 skipped, 1 failed (live assistant - Anthropic billing, known). Production build not re-run.
  - Sidebar: new "All CRM modules" section; the dashboard grid now lists all 19 modules (Contacts, Customer Portal, Documents, Communication Center, Workflow & Notifications, Administration added).
- **Step E2b (e-mail quotes with the PDF; ADR 0005)** — done 2026-10-19, not committed.
  - "Send by e-mail" / "E-mail again" (`POST /quotes/{id}/email`), `quote.email` worker job (PDF attached, portal link, Reply-To owner), e-mail status on the quote, history notes for sent/failed, retries for a down mail server.
  - Tests (run 2026-10-19): backend 843 passed (+4 opt-in skipped), ruff/mypy/import-linter clean; Vitest 202 passed; full E2E 61 passed, 1 skipped, 1 failed (live assistant - Anthropic billing, known), including a real Mailpit e-mail with the PDF. Production build not re-run.
- **Step E2c (approval limit per organisation)** — done 2026-10-19, not committed.
  - `quote_settings` table (migration 0016), `GET`/`PUT /quotes/settings`, permission `quote:settings:manage` (tenant admins), Quotes → Settings page, the quote form preview uses the limit.
  - Tests (run 2026-10-19): backend 862 passed (+4 opt-in skipped), ruff/mypy/import-linter clean; Vitest 202 passed; full E2E 62 passed, 1 skipped, 1 failed (live assistant - Anthropic billing, known). Production build not re-run.
- **Phase 10 (Documents)** — done 2026-10-19, not committed. See `docs/documents.md`.
  - Uploads with versions on accounts and deals (migration 0017, `python-multipart`), type checked by name + content, 20 MB limit, permissions `document:read/write/delete` + `portal:document:read`, Documents card on account/deal pages, portal "Documents" section, `/documents` page; the module is now "Available".
  - Sidebar: the "All CRM modules" heading was removed (the list stays); the Next.js dev badge moved to the bottom-right.
  - Tests (run 2026-10-19): backend 905 passed (+4 opt-in skipped), ruff/mypy/import-linter clean; Vitest 202 passed; full E2E (rerun 2026-10-19) 64 passed, 1 skipped, 1 failed (live assistant - Anthropic billing, known). Production build not re-run.
- **Step 17a (events + notifications; ADR 0006)** — done 2026-10-19, not committed. See `docs/workflows.md`.
  - `app/core/events.py` (publish in the same transaction, worker dispatch), events from leads/tasks/quotes/tickets/orders, `notifications` module (migration 0018), e-mail notifications, task reminder scheduler in the worker, inbox icon + Notifications page + e-mail settings; "Workflow & Notifications" module is now available.
  - Fixed: the newest-job status could pick an older job when two were created in one transaction (outbox `latest_job_status`).
  - Tests (run 2026-10-19): backend 918 passed (+4 opt-in skipped), ruff/mypy/import-linter clean; Vitest 202 passed; full E2E 66 passed, 1 skipped, 1 failed (live assistant - Anthropic billing, known). Production build not re-run.
- **Step 17b (automation rules; ADR 0006)** — done 2026-10-19, not committed. See `docs/workflows.md`.
  - `workflows` module (migration 0019: `workflow_rules`, `workflow_runs`, `automation` user type), catalogue of triggers/fields/actions, engine in the worker (events + schedules once a minute), loop depth 3 and hourly limit, per-tenant Automation identity, "Automation" pages for tenant admins.
  - Tests (run 2026-10-19): backend 965 passed (+4 opt-in skipped), ruff/mypy/import-linter clean; Vitest 205 passed; full E2E 66 passed, 1 skipped, 2 failed: the live assistant test (Anthropic billing, known) and `relationships.spec.ts` "a customer complains…" (timed out after submitting a ticket under full-suite load; passed twice when re-run alone - watch for flakiness). Production build not re-run.
- **Phase 18 part 2 (reports, builder, CSV)** — done 2026-10-19, not committed. See `docs/reports.md`.
  - `reports` module (no tables): win rate, lead conversion, revenue & quotes, support SLA; report builder over 9 record types; CSV with audit (`report.exported`) and formula-injection protection; each module supplies its own figures and export whitelist through its `api.py`; Reports pages; the module is now "Available".
  - Tests (run 2026-10-19): backend 987 passed (+4 opt-in skipped), ruff/mypy/import-linter clean; Vitest 205 passed; full E2E 67 passed, 1 skipped, 4 failed: the live assistant test (Anthropic billing, known), two menu lists that needed "Reports" and the quotes journey that timed out on a slow machine - after fixing the lists, `workflow1` + `quotes` specs re-run: 12 passed. The full suite was not re-run end to end after that fix. Production build not re-run.
- **Online deployment, step D1 (ADR 0007)** — prepared 2026-10-19, nothing is online. See `docs/deployment.md`.
  - `netlify.toml`; `backend/Dockerfile` (API + worker); `infrastructure/keycloak/Dockerfile.production` + generated `realm-crm-production.json` (no users); tests for requirements and the production realm; production web build is clean.
  - Fixed: `requirements.txt` lacked PyJWT/cryptography (a clean install crashed).
  - Still needed: D2 staging and D3 go-live (accounts, domain, secrets - owner's actions), direct-to-bucket uploads if hosting limits require.
- **Netlify 404 fix and documentation audit** — done 2026-10-20, not committed. See `docs/deployment.md`.
  - `netlify.toml` sets `publish = ".next"` (the Next.js adapter deploys the server build, not
    static files); a "Page not found" troubleshooting section was added to `docs/deployment.md`.
  - Production web build re-run on 2026-10-20: clean, including with `.env.local` removed
    (Netlify's empty environment). Every page is server-rendered (only /_not-found is static),
    so Netlify's Next.js adapter is required - static hosting cannot serve the app.
  - Documentation drift fixed in `architecture.md`, `implementation-plan.md`, `docs/auth.md`
    and `docs/frontend.md`.
  - New generated `docs/inventory.md` and `backend/scripts/report_inventory.py` (command in the
    table above): current API, database, route and test counts; the database part is skipped
    when PostgreSQL is unreachable.
- **PostgreSQL Row-Level Security (ADR 0009)** — done 2026-10-23 and **merged into `main`** (PR #1, then the steps that followed it). See `docs/rls-audit.md`.
  - ENABLE + FORCE RLS and a tenant policy on every table with `tenant_id`: 47 at migration 0036, **50** since the contract tables of 0037 (migrations 0022, 0029-0037); `leads` also checks the owner scope; narrow SECURITY DEFINER functions for login, sign-up, the worker claim and the metrics counts (0030-0032, 0036). The worker stays on `crm_app`.
  - Test bootstrap: worlds are built as `crm_owner` (`committed_world`) and committed; API calls and assertions run as `crm_app`. Guard test `test_rls_tenant_tables.py` fails any new tenant table without RLS.
  - Fixed on the way: `POST /platform/tenants` returned 500 under users RLS; `/metrics` queue gauges were always 0.
  - Tests (run 2026-10-23): backend 1150 passed (+4 opt-in skipped), ruff/mypy/import-linter clean. Re-checked 2026-10-24 on the development database at 0037: `rls_audit` 50/50 protected, 0 tenant tables readable without a tenant context, `crm_app` without bypass. Full Playwright run on the merged code (2026-10-24): 73-74 of 77 passed; the failures were the live assistant test (now opt-in) and timing flakes that pass when run alone.
- **Pending:**
  - Assistant live check against real Claude. Blocked by Anthropic billing ("credit balance too
    low"); test with `python -m scripts.check_anthropic`.
  - Teams (rest of Phase C; RLS, the outbox, worker and reminder e-mails are done).
  - Modules not started: marketing (Phase 16), integrations (Phase 19),
    staff AI assistant (Phase 20b/20c: knowledge base, voice).
  - Full end-to-end suite re-run after the latest fixes (last recorded 2026-10-19: backend 987,
    Vitest 205, Playwright 67 with known failures - live assistant, one slow test).
- **Current phase:** Online deployment (ADR 0007) - D1 preparation done; D2 staging and D3
  go-live wait for the owner's accounts, domain and secrets. The Netlify "Page not found" (404)
  is being resolved: `netlify.toml` now sets `publish = ".next"`; the next check is the
  **Deploy summary Functions count** (steps in `docs/deployment.md`).
- **Contracts and renewals (C1-C4)** - built 2026-10-23 and **merged into `main`** (PR #4). See `docs/contracts.md`.
  - Migration 0037 (3 tables, forced RLS, insert-only history), API at `/api/v1/contracts`, worker expiry
    sweep + auto-renew draft + one renewal reminder per renewal date, notifications to owner and creator,
    screens (list, detail, form, account card, menu entry, module tile), account-search route handler.
  - Tests (run 2026-10-23): backend contracts 64 + 7 worker tests (full suite below); Vitest 247; Playwright
    `contracts.spec.ts` 3 passed.
- **Communication Center (Phase CC, ADR 0012)** - started 2026-10-24. CC0 (ADR + phase plan in
  `implementation-plan.md`) done on branch `feat/communications`.
  - CC1 (2026-10-24): `communications` module with `email_templates` + `email_messages`
    (migration 0038, forced RLS, messages can't be deleted), 4 `communication:*` permissions.
    Tests (run 2026-10-24): backend 1284 passed (+4 opt-in skipped); ruff, mypy, import-linter
    clean. Master plan for the PDF work: `docs/master-plan.md`.
  - CC2 (2026-10-24): `POST /api/v1/communications/emails` (lead or contact, address from the
    record, related account/deal must be the contact's, withdrawn consent refused, 200 per
    person per hour via `CRM_COMMUNICATION_EMAILS_PER_HOUR`), `GET /emails/{id}`,
    `communication.email` worker job (Reply-To = sender, safe to run twice, consent re-checked),
    failure → `communication.email_failed` event → notification; e-mail entry on the timeline;
    audit `email.queued`. Tests (run 2026-10-24): backend 1326 passed (+4 opt-in skipped);
    ruff, mypy, import-linter clean.
  - CC3 (2026-10-24): templates at `/api/v1/communications/templates` (list, get, create,
    PATCH incl. deactivate/reactivate with version check, preview for a lead/contact or sample
    values) and `/placeholders`; 6 fixed placeholders filled in one pass (no engine, no
    re-expansion, no line breaks in subjects); unknown/broken placeholders → 422
    `unknown_placeholder`; agents see active templates only. Tests (run 2026-10-24): backend
    1369 passed (+4 opt-in skipped); ruff, mypy, import-linter clean.
  - CC4 (2026-10-24): `GET /communications/history` (one lead/contact/account/deal under that
    record's read rules; an account includes its contacts and deals), `GET /communications/emails`
    (read:all / read:own, filters in SQL), `POST /communications/emails/received` (log a received
    e-mail; no sending, no consent or limit check); migration 0039 adds `email_messages.seq` for a
    reliable newest-first order. Tests (run 2026-10-24): backend 1391 passed (+4 opt-in
    skipped); ruff, mypy, import-linter clean. Branch pushed to GitHub (draft PR #13).
  - CC5 (2026-10-25): screens - "Send e-mail" / "Log a received e-mail" dialog (template
    preview fills subject and text, text stays editable, kept on server errors; contacts
    without address or consent can't be chosen), E-mails card on lead, contact, account and
    deal pages, Communication Center page (`/communications`, filters, paging), Templates pages
    for managers (list, new, edit, deactivate/reactivate, placeholder list), "E-mail" menu
    entry, module tile "Available". Tests (run 2026-10-25): Vitest 295 passed (30 new); lint,
    typecheck and production build clean. Browser check (2026-10-25, as alpha.manager, dev
    database at 0039): menu entry, Communication Center list + status filter, template create
    (unknown placeholder refused, text kept), edit, deactivate/reactivate, contact card
    without address (blocked message), Send dialog with template preview, e-mail delivered to
    Mailpit with Reply-To the sender, status Sending -> Sent, log received e-mail (empty form
    refused), account page contact list - all worked, no console errors.
  - CC6 (2026-10-25): Playwright `e2e/communications.spec.ts` (template -> send -> real Mailpit
    e-mail with Reply-To the sender -> log the reply -> Communication Center; who may not see
    what), `docs/communications.md`, refreshed `docs/inventory.md` (203 API operations). The
    e-mail dialog now builds its form on first open (no hidden duplicate "Subject" fields on
    record pages). Menu/tile lists in `workflow1.spec.ts` include the new entry.
    Full run (2026-10-25): backend 1391 passed (+4 opt-in skipped); ruff, mypy, import-linter
    clean; Vitest 295 passed; Playwright 77 passed, 2 skipped (live assistant, slow refresh),
    0 failed; lint, typecheck and production build clean. **Communication Center complete**,
    approved by the owner and **merged into `main` (PR #15, 2026-10-25)**.
- **Public website chat (BP-01, Phase PC, ADR 0013)** - started 2026-10-25 on branch
  `feat/public-chat-save-lead`. PC0: ADR 0013 accepted + phase plan. Order of all PDF work:
  `docs/master-plan.md`.
  - PC1 (CRM-104, 2026-10-25): `DeepSeekChatModel` supports tool calling (tools as OpenAI
    functions, `tool_calls` -> `ToolUse`, results as `role: "tool"`, broken arguments -> `{}`);
    Anthropic unchanged; injectable HTTP function for tests. Tests (run 2026-10-25): backend
    1403 passed (+4 opt-in skipped), incl. 12 new in `test_deepseek_tools.py`; ruff, mypy,
    import-linter clean.
  - PC2 (CRM-105, 2026-10-25): lead fields `property_type`, `budget_min_inr`, `budget_max_inr`
    (BIGINT whole rupees, >= 0, <= 1 lakh crore, min <= max) and `location` (migration 0040 with
    database checks; `422 budget_out_of_order` when a one-sided change breaks the order); lead
    form "Property wishes" (accepts 12000000 / 1,20,00,000 / 1.2 Cr / 80 L), lead page shows
    "₹1.2 Cr – ₹1.5 Cr"; docs/leads.md. Dev database at 0040. Tests (run 2026-10-25): backend
    1421 passed (+4 opt-in skipped); Vitest 327 passed; Playwright 78 passed, 2 skipped, 0 failed
    (new `lead-property.spec.ts`); ruff, mypy, import-linter, lint, typecheck, build clean.
  - PC3 (CRM-106a, 2026-10-25): `public_chat` module - `POST /api/v1/public/chat` (only with
    the `X-Public-Chat-Key` server key, else 404; tenant from `CRM_PUBLIC_CHAT_TENANT_SLUG`),
    tables `public_chat_sessions` + `public_chat_messages` (migration 0041, forced RLS; token
    stored as SHA-256, visitor address as a keyed hash), one tool `save_lead` (lead created as
    the Automation identity, unassigned, source web, one per conversation), guardrails +
    honeypot, limits (per address, per conversation, per day), at most 2 tool rounds,
    providers deepseek | anthropic | fake (fake refused in production); `assistant/api.py`
    added. Dev database at 0041. Tests (run 2026-10-25): backend 1471 passed (+4 opt-in
    skipped), 50 new; ruff, mypy, import-linter clean.
  - PC4 (CRM-106a, 2026-10-25): event `public_chat.lead_captured` (lead + conversation ids)
    → notification to every sales manager; `GET /api/v1/public-chat/leads/{id}/transcript`
    (lead read permission + the lead's own read rules, else 404) and a "Website chat" card on
    the lead page; worker deletes conversations without a lead after
    `CRM_PUBLIC_CHAT_RETENTION_DAYS` (30) quiet days. Fixed on the way: the worker could not
    see any lead (leads RLS needs a user + scope, the worker bound only the tenant), so
    `lead.assigned` notifications and lead workflow rules silently did nothing - new
    `identity_api.bind_reader`; worker tests now clear the request's settings first.
    Tests (run 2026-10-25): public-chat 60 passed (10 new), notifications + workflows 32
    passed; ruff, mypy, import-linter clean; Vitest 330 passed (3 new); lint, typecheck clean.
    Full backend suite (finished after the commit): 1481 passed (+4 opt-in skipped).
  - PC5 (CRM-106b, 2026-10-25): public page `/chat` (no sign-in, privacy notice, plain-text
    answers, hidden honeypot field, works on a phone) and route handler `/api/public-chat`
    (adds the server key and the visitor's address - Netlify's own header first - keeps the
    token in the httpOnly `crm_chat` cookie, path `/api/public-chat`, 30 days; one retry when
    the old conversation was cleaned up); `proxy.ts` lets both through; both are 404 without
    `PUBLIC_CHAT_SERVER_KEY`. Browser check (phone size, fake model): conversation -> details
    saved, token not readable by page JavaScript, nothing in localStorage.
  - PC6 (2026-10-25): Playwright `e2e/public-chat.spec.ts` (visitor -> lead -> manager
    notification -> transcript on the lead page; agent can't see it; honeypot refused),
    `docs/public-chat.md`, refreshed `docs/inventory.md`. Full runs (2026-10-25): backend 1481
    passed (+4 opt-in skipped; no backend code changed after that run); Vitest 347 passed;
    Playwright 79 passed, 2 skipped, 1 failed - the new chat journey, refused by the
    3-conversations-per-address limit because every local run shared one address; fixed by
    giving each run its own test address, then the spec passed twice (2 + 2). The full
    Playwright suite was not re-run after that fix. Lint, typecheck, production build clean.
    **BP-01 complete**: approved by the owner and **merged into `main` (PR #17,
    2026-10-25)** after both GitHub CI runs passed.
- **Approval queue for AI actions (BP-05, Phase AP, ADR 0014)** - started 2026-10-25 on branch
  `feat/agent-approvals`. AP0: ADR 0014 (accepted 2026-10-25) + phase plan.
  - AP1 (2026-10-25): `approvals` module - `agent_actions` (migration 0042, forced RLS, DELETE
    revoked, database check against self-decision), permissions `agent_action:propose` (all
    staff roles) / `agent_action:approve` (sales managers, tenant admins), catalogue
    `lead.set_status` / `lead.assign` / `activity.create_task` (lead, account or contact),
    service propose / approve / reject: payload validated (nothing extra), record must be
    visible to the requester (else 404), no self-approval (admins too), row lock + version +
    expiry check, the action runs through the owning module's api.py as the approver in a
    savepoint (refused -> "failed", nothing changed), audit `agent_action.*`;
    `leads_api.assign_lead`, contact tasks in `activities_api.create_task`. No endpoints yet
    (AP2). Dev database at 0042, `rls_audit` 55/55 protected. Tests (run 2026-10-25): backend
    1511 passed (+4 opt-in skipped), 30 new in `test_approvals.py`; ruff, mypy, import-linter
    clean.
- **Next planned, in order:** BP-05 (in progress), BP-10, BP-11 (rest of AI Track A1), then
  BP-04 leftovers and the AI tracks A2-A4, Marketing
  (Phase 16), Integrations (Phase 19). Teams come before the features that need them and need
  an ADR.
