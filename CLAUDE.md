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
| Add new Keycloak clients from realm-crm.json to the running Keycloak (non-destructive) | `python -m scripts.keycloak_add_clients` (in `backend`, venv active) | ADR 0015 |
| Install the CRM MCP server (once) | `cd mcp-server && uv sync` | ADR 0015 |
| MCP server tests (unit / + live) | `cd mcp-server && uv run pytest -m "not live"` / `uv run pytest` | ADR 0015 |
| Connect Claude Code to the CRM (read-only) | `claude mcp add crm-lead -- E:\crm-lead\mcp-server\.venv\Scripts\crm-mcp.exe` | ADR 0015 |
| Seed local test data (fictional) | `python -m scripts.seed_dev_data` (in `backend`, venv active) | Phase 4 |
| Seed fictional knowledge documents (RAG R1.6) | `python -m scripts.seed_knowledge_demo` (in `backend`, venv active) | RAG R1 |
| Keycloak admin console | http://localhost:9080/admin (credentials in `infrastructure\.env`) | Phase 4 |
| Local e-mail inbox (Mailpit) | http://localhost:8025 — invitations, verification, password reset | ADR 0004 |
| Run background worker (own CMD window) | `python -m app.worker` (in `backend`, venv active); `--once` runs due jobs and exits | ADR 0005 |
| File store (SeaweedFS, S3 API) | `127.0.0.1:9333`, keys in `infrastructure\.env`; started by `docker compose up -d` | ADR 0005 |
| Open the CRM to other devices on your network (see docs/network-access.md) | `python -m scripts.network_mode on <PC address>` / `off` / `status` (in `backend`, venv active), then `cd frontend && npm run dev:network` | Network mode |
| Run the AI agent evaluation cases (BP-10) | `python -m scripts.eval_agents --provider fake` (in `backend`, venv active); `--estimate` shows the cost of a real-model run; real models need `set CRM_RUN_LIVE_EVALS=1` | BP-10 |
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
  - AP2 (2026-10-25): API `GET /api/v1/approvals/actions` (approvers: the organisation's, filter
    `status` / `mine`; others: their own; paging; record name only if the reader may see it),
    `GET /actions/{id}`, `POST /actions/{id}/approve` (version + note) and `/reject` (note
    required); no endpoint creates proposals (only AI features, through the service). Events
    `agent_action.proposed` -> notification to everyone who may approve except the requester,
    `agent_action.decided` -> the requester (approved / rejected / could not be carried out /
    expired); worker marks overdue proposals expired; at most `CRM_AGENT_ACTION_PENDING_PER_USER`
    (20) waiting per person (429 `agent_action_limit_reached`), expiry
    `CRM_AGENT_ACTION_EXPIRY_DAYS` (7). Tests (run 2026-10-25): backend 1523 passed (+4 opt-in
    skipped), 12 new in `test_approvals_api.py`; ruff, mypy, import-linter clean; OpenAPI
    exported.
  - AP3 (2026-10-25): the staff assistant (`POST /assistant/ask`) now passes its tools to the
    model (before, it passed none) and has three proposing tools - `propose_lead_status`,
    `propose_lead_assignment`, `propose_follow_up_task`. They only create a pending proposal
    (savepoint; record must be visible to the asker, strict arguments, status never
    "converted"); at most 3 proposals per question and the per-person pending limit apply; the
    tool result tells the model nothing has changed. The answer has a new `proposals` list
    (id, description, status, link `/approvals/{id}`), stored by one commit in the router.
    Scripted model, no paid key. Tests (run 2026-10-25): backend 1534 passed (+4 opt-in
    skipped), 11 new in `test_assistant_proposals.py`; ruff, mypy, import-linter clean;
    docs/assistant.md.
  - AP4 (2026-10-25): screens. Menu entry "Approvals" (everyone with `agent_action:propose` or
    `:approve`) and module tile "AI Approvals". `/approvals`: tabs Waiting (approvers only) /
    My proposals / History with a status filter and paging, one card per proposal (what, record
    link, why, who asked, expiry, how it ended) with Details / Reject / Approve; `/approvals/{id}`
    (notifications link here); Reject needs a note, Approve may have one, both confirm first and
    show the API's reasons in plain words (already decided, changed, expired, own proposal, record
    not visible). "AI proposals" card on the lead, account and contact pages (waiting ones for
    that record; new `target_id` filter on the list API), a card with the number waiting on the
    Automation page, and the assistant's answer lists what it proposed ("Nothing has changed
    yet"). Everything the model or a person wrote is shown as plain text. Tests (run
    2026-10-25): backend 1535 passed (+4 opt-in skipped), ruff, mypy, import-linter clean; Vitest 367 passed (20 new in `approvals.test.tsx` and
    `assistant-proposals.test.tsx`; two module-count tests updated); lint, typecheck and
    production build clean; Playwright `workflow1` + `notifications` 10 passed (menu and tile
    lists updated); browser check with a demo proposal as manager, agent and admin worked.
    A demo proposal ("Demo proposal (fictional)") is left waiting in the dev database.
  - AP5 (2026-10-25): `CRM_AI_PROVIDER=fake` - a scripted staff assistant (`assistant/fake_llm.py`,
    understands "mark lead <id> as contacted because ...", refused in production) so the queue
    can be tried without a paid key; Playwright `e2e/approvals.spec.ts` (agent asks the
    assistant -> a proposal waits and the lead is unchanged -> the asker can't approve and a
    colleague can't see it -> a manager approves -> only then the lead changes -> notifications;
    a rejection needs a reason and changes nothing; runs only with `E2E_FAKE_ASSISTANT=1` and the
    fake provider); `docs/approvals.md`; refreshed `docs/inventory.md`.
    **First real-model try (DeepSeek, 2026-10-25, by hand with a script, not an automated test):**
    asked as an agent by lead id and by lead name, `deepseek-chat` called the proposing tool,
    a pending proposal was stored, the lead stayed unchanged and the answer said nothing had
    changed yet and a manager must approve. Two more demo proposals are waiting in the dev
    database (fictional alpha-demo leads). Claude (Anthropic) not tried: account has no credit.
    Full runs (2026-10-25): backend 1547 passed (+4 opt-in skipped), ruff, mypy, import-linter
    clean; Vitest 367 passed; lint, typecheck, production build clean; Playwright 79 passed,
    2 skipped, 3 failed in the full run - `communications` and `lead-property` timed out while
    the backend test suite ran at the same time, `portal-knowledge` failed because the fake
    provider was switched on for the run (that screen asks the assistant model); all three
    passed when rerun alone with the real provider (4 tests). The whole suite was not rerun
    in one piece after that. **BP-05 complete**: approved by the owner and **merged into `main`
    (PR #18, 2026-10-25)** after both GitHub CI runs passed.
- **BP-04 leftovers (2026-10-25)** - done and **merged into `main` (PR #19)**. The user menu shows a badge
  "Own leads only" (agents) or "All leads in your organisation" (managers, admins), none for roles
  without lead access and in the customer portal (display only: the database decides). Playwright
  (`workflow1.spec.ts`): agent 2 creates a lead, agent 1 typing its address and a made-up lead
  address both get "Page not found", the menu badges are right, the manager opens the lead. Tests
  (run 2026-10-25): Vitest 373 passed (6 new); lint, typecheck, production build clean; Playwright
  `workflow1` + `workflow2` + `workflow3` + `portal` 27 passed. Backend not touched. The whole
  Playwright suite was not rerun for this small change.
- **Agent evaluation harness (BP-10, Phase EV)** - started 2026-10-25 on branch
  `feat/agent-evals`. EV0: design note `docs/agent-evals.md` + phase plan (documents only); owner
  approved it 2026-10-25 with three decisions: no scorecard endpoint, one paid DeepSeek run at the
  end, scripted-model cases are a hard CI gate (real-model results only a report).
  - EV1 (2026-10-25): package `backend/agent_evals/` (outside `app`, not in the Docker image) with
    argument matchers (equal, any, any_uuid, one_of, matches, contains, absent), the case format
    and loader (`evals/agents/*.json`; unknown fields, typos in tool names, broken matchers,
    duplicate ids and bad placeholders stop the load; a case may be marked `live: false` when it
    forces a bad call on purpose), the dataset hash, scoring of a conversation (tool order and
    arguments, forbidden tools, outcome, wanted and banned words, "claimed done" detector, call
    limit) and a deterministic scorecard (totals, tool precision and recall, argument accuracy);
    4 starter staff-assistant cases. Nothing plays a conversation yet (EV2). Tests (run
    2026-10-25): backend 1642 passed (+4 opt-in skipped), 95 new (pure Python, no database, no
    key); ruff, mypy, import-linter clean.
  - EV2 (2026-10-25): `agent_evals/runner.py` plays a staff-assistant case through the REAL
    assistant and the real test database with only the model scripted (`ScriptedModel`,
    `RecordingModel` reads every tool call and how the CRM answered from the tool results; a case
    that ends before a result came back is a loud error). 15 cases in
    `evals/agents/staff_assistant.json` (reading, proposing status / assignment / follow-up tasks,
    not found, "converted", extra argument, support assignee, fourth proposal, made-up approve
    tool, injection and card-number questions, support agent reading leads); every case also gets
    two checks it cannot skip - no direct change in the CRM and proposals stored exactly as
    reported. `tests/db/test_agent_evals_staff.py` runs them in CI (hard gate) and proves the gate
    can fail (wrong expectation, forbidden tool, "done" claim, raised proposal limit). Findings, not
    fixed (BP-10 only measures): the card-number guardrail wrongly refuses about 1 in 600 lead
    ids pasted into a question; a support agent asking about "leads" gets a bare 403. Tests (run
    2026-10-25): backend 1686 passed (+4 opt-in skipped), 44 new; ruff, mypy, import-linter clean.
  - EV3 (2026-10-25): the runner also plays the customer portal assistant (the customer's real
    conversation, several messages in one) and the public website chat (an anonymous visitor, the
    token kept between messages); 19 more cases (`portal_assistant.json` 9, `public_chat.json` 10;
    34 in all): a customer's own accounts, a staff tool refused, a ticket only PREPARED for the
    customer to confirm, other customers' account and a made-up order "not found", short subject
    and extra argument refused, one lead saved, a greeting saves nothing, invalid phone and budget
    out of order refused, one lead per conversation, no CRM data ever given, injection and
    card-number questions stopped before any model. Extra checks no case can skip: portal - no
    ticket created and pending actions match; public chat - exactly one unassigned web lead when
    one was saved, nothing else changed. `tests/db/test_agent_evals_portal.py` and
    `test_agent_evals_public_chat.py` run them in CI and prove the gate can fail (a staff tool in
    the customer's tools, broken account access, a second lead in one conversation, a "done"
    claim). Tests (run 2026-10-25): backend 1719 passed (+4 opt-in skipped), 33 new; ruff, mypy,
    import-linter clean.
  - EV4 (2026-10-25): cited answers in CI without a paid key. `agent_evals/rag.py` +
    `rag_cases.py` play 14 cases (`evals/rag/ci_cases.json`) through the REAL grounded-answer
    pipeline and the real test database; only two stand-ins: `HashingEmbedder` (deterministic, no
    model download) and a scripted answer that cites documents by title (`{cite:Returns policy}`;
    the pipeline decides the numbers). Scored with the existing metrics plus: outcome (answered /
    not_found with NO model call / ungrounded), documents cited, documents that must never appear.
    Cases: the four existing questions + a cleaning question, three unanswerable questions, an
    uncited answer and an invented citation (never shown), a negative control (an answer obeying
    the poisoned 50% discount is cited, so the metrics must flag it), another organisation's agent
    and a customer (visibility). CI threshold 0.25 chosen from measurements (answerable 0.32-0.76,
    unanswerable 0.00-0.18), kept 0.05 clear on both sides by a test. `tests/db/test_agent_evals_rag.py`
    proves the gate can fail (missing citation check, threshold that lets everything through,
    internal documents reaching a customer, wrong document cited). Tests (run 2026-10-25): backend
    1766 passed (+4 opt-in skipped), 47 new; ruff, mypy, import-linter clean.
  - EV5 (2026-10-26): command line `python -m scripts.eval_agents --provider fake|deepseek|anthropic`
    (`--suite`, `--only`, `--out`, `--summary`, `--baseline`, `--render`, `--estimate`); plays in the
    development database as people found by role, one rolled-back transaction, each case in its own
    savepoint; scripted = every case, strict, exit 1 on any failure; real model = `live` cases,
    lenient scoring (expected calls in order, extras allowed), a report unless `--baseline` shows a
    regression; paid providers need `CRM_RUN_LIVE_EVALS=1`; `--estimate` is free (26 live cases,
    about 80 calls, about $0.04 at published DeepSeek prices). The pytest files and the CLI share
    `agent_evals/world.py`, `play.py`, `suite.py`; CI writes the scorecard into the job summary and
    uploads it. Third finding: the card-number guardrail also refuses the seeded demo users' ids
    (a1000000-0000-4000-8000-00000000000N); the world uses clean ids / stand-in colleagues. Tests
    (run 2026-10-26): full backend 1816 passed, 4 opt-in skipped, 1 failed
    (`test_requirements`: the new script imports `agent_evals`, which is not in the image) - fixed
    and that file re-run alone: passed; the whole suite was not re-run after that one-line fix.
    ruff, mypy, import-linter clean. CLI on dev data: 4 suites, all cases passed, twice the same
    scorecard. The one paid DeepSeek pass was run 2026-10-26 with the owner's yes (about $0.04): baseline `backend/evals/baseline/deepseek.json` - 15 of 26 live cases passed, 0 forbidden-tool violations, 0 false "done" claims, tool precision/recall 46 %, argument accuracy 41 %; most failures are missing phrases or a tool not called (see docs/agent-evals.md).
- **CRM MCP server standard (BP-11, ADR 0015)** - owner approved ADR 0015 on 2026-10-26 (all five
  clients, no hosted endpoint now, old worktree left alone). MCP0: ADR 0015 (+ the old, unmerged
  ADR 0010 text kept as `docs/adr/0015a-original-crm-mcp-decision.md`). MCP1 (2026-10-26): the
  existing read-only server was found uncommitted in another worktree and is now on branch
  `feat/mcp-standard`: `mcp-server/` (8 read-only tools, PKCE sign-in, `uv.lock`), Keycloak
  client `crm-mcp` (not in the production realm), `scripts/keycloak_add_clients.py`, API access
  log `client_id` from the verified token's `azp`, new CI job `mcp-server`. Fixed on the way: the
  server's default Keycloak address was still port 8080 (Keycloak moved to 9080). Tests (run
  2026-10-26): mcp-server 44 unit + 7 live (real Keycloak + API) passed, ruff and mypy strict
  clean; backend realm/client-id tests 16 passed, ruff, mypy, import-linter clean. The full
  backend suite was not re-run (only a script, two small API edits and tests changed). MCP2-MCP4
  not started; the connector in `~/.claude.json` still points at the old worktree until the
  owner confirms.
  - MCP2 (2026-10-26, branch `feat/mcp-contract`): `docs/mcp-tools.md` (generated tool table + rules
    + version rule), committed `mcp-server/contract/catalogue.json`, `crm_mcp/catalogue.py` with
    `python -m crm_mcp.catalogue [--write]`. Tests fail when the live tools, the snapshot or the
    page differ, when a tool is not read-only / badly named / without endpoints / page size above
    50, and `--write` refuses a change whose version bump is too small (breaking = new major,
    before 1.0 new minor). Tests (run 2026-10-26): mcp-server 88 passed (37 new, 7 live included),
    ruff and mypy strict clean. MCP3-MCP4 not started.
  - MCP3 (2026-10-26, branch `feat/mcp-clients`): `tests/test_stdio_handshake.py` starts the real
    program over stdio and checks the handshake, the documented read-only tools, no resources or
    prompts, and a clear start-up error on a bad address (stdout stays empty); `docs/mcp-clients.md`
    with set-up for Claude Code, Claude Desktop, Cursor, VS Code and JetBrains (only Claude Code
    was actually used; the others follow each product's documented format and are marked not
    tested). MCP Inspector 2.12.0 (CLI mode) listed the same 8 tools. Tests (run 2026-10-26):
    mcp-server 92 passed (4 new, 7 live included), ruff and mypy strict clean. Finding, not
    fixed: a tool call with an invalid ID still opens the sign-in first (input is checked after
    sign-in). MCP4 not started.
  - MCP4 (2026-10-26, branch `feat/mcp-hardening`): hardening review. Input checked before sign-in
    (a bad ID no longer opens the browser); free text cut at 2,000 characters with a marker;
    at most 60 API calls per minute from the server (`CRM_MCP_MAX_CALLS_PER_MINUTE`); HTTP 429,
    non-JSON answers, unreachable Keycloak and unexpected errors become short safe messages
    (nothing internal, no token); prompt-injection tests (three attack texts stay under `data`,
    envelope fixed, no tool can write). Forged `azp`: already covered by the backend tests
    (`test_request_client_id.py`: a rejected token cannot choose its name, odd names logged as
    `invalid`). Tests (run 2026-10-26): mcp-server 116 passed (24 new, 7 live included); the
    new tests were shown to fail when the changes are undone; ruff and mypy strict clean.
    **BP-11 steps MCP0-MCP4 complete**; MCP5 (propose tools) and MCP6 (hosted endpoint) need
    separate approval.
- **Agent registry, budgets and kill switch (BP-14, Phase AG, ADR 0016)** - started 2026-10-26 on
  branch `feat/agent-registry`. AG0: ADR 0016 (proposed) + phase plan, documents only; five
  questions for the owner (token budget, default on with a cap, public-chat "off" sentence, who
  switches, platform switch `CRM_AI_DISABLED`); owner approved it with the recommended answers
  (docs PR #25).
  - AG1 (2026-10-26, branch `feat/agents-module`): module `agents` - catalogue of the four AI
    agents (tools checked against the real tools by a test), tables `agent_settings` +
    `agent_usage` (migration 0043, forced RLS, usage rows can't be deleted), permissions
    `agent:read` (tenant admin, sales manager) / `agent:manage` (tenant admin), settings
    `CRM_AI_DISABLED` and `CRM_AGENT_DEFAULT_MONTHLY_TOKENS` (2,000,000), services
    (`check_can_call`, atomic `record_usage` with a once-a-month 80 % flag, audited
    `update_settings` with version check and tools-only-narrowing). Nothing calls it yet (AG2).
    See `docs/agents.md`. Dev database at 0043.
  - AG2 (2026-10-26, branch `feat/agents-governed`): `governed(model, ...)` in front of the four
    call sites (staff assistant, portal assistant, knowledge answers, website chat): refuses when
    the platform switch is on, the agent is off or its month's tokens are used up (503
    `agent_unavailable` / `agent_budget_reached`; the website chat answers with a fixed "resting"
    sentence and saves no lead), offers only the allowed tools, drops a removed tool's call, meters
    tokens, counts refusals (`crm_ai_refusals_total`, no tenant label). BP-10 harness: `governance`
    block, outcomes `agent_off` / `over_budget`, `expect.model_called`, 8 new cases. A made-up tool
    name still reaches the feature's own refusal (existing `staff-no-approve-tool` case unchanged).
  - AG3 (2026-10-26, branch `feat/agents-api`): API `GET /api/v1/agents`, `GET /{key}`, `PATCH /{key}` (tenant admins change, sales managers read; version check; unknown tool / bad budget / empty change 422; tenant never from the client), audit `agent.updated`, events `agent.switched` (only when the switch flips) and `agent.budget_warning` (once per month and agent) -> notifications to the other tenant admins, both types on the notification settings page; OpenAPI and inventory refreshed. See `docs/agents.md`.
  - AG4 (2026-10-26, branch `feat/agents-page`): page **AI agents** at `/automation/agents` (menu entry for tenant admins and sales managers, card on the Automation page): a card per agent with its state in words, usage bar and tool count; tenant admins get the settings form (switch, monthly token budget, tools); managers read only. Notification links now resolve. Tests (run 2026-10-26): Vitest 402 passed (29 new); lint, typecheck, production build clean; Playwright `agents` (new) + `workflow1-3` + `automation` 22 passed, 1 failed (`workflow3` manager accounts) that passed when re-run alone (load flake as before); backend untouched in AG4. The API on port 8000 was restarted from this worktree to run the journey. **Phase AG (BP-14) complete.** Tests (run 2026-10-26): full backend 1971 passed (+4 opt-in skipped), 31 new; 2 time-dependent tests (`test_dashboard_api` support refusal, `test_pipeline_activities_api::test_reminders_and_overdue`) failed in that run, which lasted almost 11 hours because the PC slept - both files re-run alone: 69 passed; ruff, mypy, import-linter clean. Tests (run 2026-10-26): full backend 1941 passed (+4 opt-in skipped), 1 failed - an old unit test that gave the staff service a fake session (fixed: it now bypasses the gate; that file re-run alone passed, the whole suite not re-run after that fix); ruff, mypy, import-linter clean; the eval scorecard on the dev data passed all cases. With the gate removed, 14 of the 16 site tests and the 8 new cases fail (the other 2 are expected to pass). Tests (run 2026-10-26): full backend 1882 passed (+4 opt-in skipped), 53 new; ruff, mypy, import-linter clean. Atomicity of the usage upsert is checked by looking at the SQL, not by a parallel run.
- **Sentinel action verifier (BP-21, Phase SN, ADR 0017)** - ADR accepted 2026-10-26 with the
  recommended answers (every link blocked, 10 proposals and 3 assignments per hour, re-check at
  approval, warnings on the card only, "Safety check" on screen). SN1 (2026-10-26, branch
  `feat/sentinel-rules`): `app/core/screening.py` (clean untrusted text, report instruction
  phrases) and `approvals/sentinel.py` (words, pattern, state, tenant and the record's own text as
  pure rules; fails closed; re-check mode for approval), attack library
  `backend/evals/attacks/library.json` (55 texts), `docs/sentinel.md`.
  Tests (run 2026-10-26): 288 new pure tests passed; with the link rule and one instruction
  pattern disabled 19 fail; ruff, mypy, import-linter clean. The full backend suite was not
  re-run (only new files were added).
  - SN2 (2026-10-27, branch `feat/sentinel-hook`): the Sentinel runs inside `approvals.propose()`
    (facts from the database: the lead's state and free text, the asker's hourly counts, an
    identical waiting proposal, the assignee's organisation) and `approve()` (state and tenant
    rules again; a stale proposal ends as failed); migration 0044 `agent_actions.verification`;
    `ProposalBlockedError` (422 `proposal_blocked`), audit `agent_action.blocked` written by the
    caller after its savepoint (the staff assistant does), metric `crm_ai_sentinel_findings_total`,
    settings `CRM_SENTINEL_*`, `warnings` on every proposal in the API; OpenAPI and inventory
    refreshed; dev database at 0044. Existing tests adjusted: two (proposals made twice on one
    lead were duplicates; the failed approval now names "already has this status"). Tests (run
    2026-10-27): 30 new database tests passed; approvals, approvals API, assistant proposals and
    the new file together 85 passed; ruff, mypy, import-linter clean. The full backend run took
    12h39 because the PC slept: 2278 passed, 12 failed, 2 errors - the 2 approvals failures were
    real and are fixed; the other failures were time- and connection-dependent (invoices
    overdue/due dates, dashboard, reminders, contracts, knowledge threshold, two orders setup
    errors). Re-run alone afterwards: those six files 200 passed, 1 failed (an expired test token in a 2h49 run) and that test passed when run alone.
  - SN3 (2026-10-27, branch `feat/sentinel-input`): `guardrails.inspect_input` now cleans what a
    person types (hidden characters, markup, images, floods; links and addresses stay) and refuses
    a hidden or split instruction, hidden card numbers and an empty result - `decision.clean` is
    used by the staff assistant, the portal assistant and the website chat; record text in the
    staff prompt and in the results of the staff and portal tools goes through `clean_records`
    (links out, addresses stay) and the model is told when a record reads like an instruction;
    the approval card shows the stored warnings as **Safety check** above the buttons. Tests (run
    2026-10-27): 77 new backend tests (pure input screening incl. the attack library, plus the
    three entrances and the prompt through the real API); Vitest 406 passed (4 new); frontend lint,
    typecheck and production build clean; ruff, mypy, import-linter clean. The full backend run took
    7h25 because the PC slept: 2356 passed, 3 failed (a super-admin listing test, a payment
    reversal and the reminders test, all time-dependent) - re-run alone: 3 passed. Playwright was
    not re-run (the card change is covered by component tests; the approvals journey needs the
    scripted assistant).
  - Verification artifacts (BP-29, Phase VA, ADR 0018) - ADR accepted 2026-10-27 with the recommended
    answers (changes and outcome in the normal proposal read, no plan for old proposals, CSP
    report-only first, every link to another site removed from answers, only cleaned text plus a note
    in a lead). VA1 (2026-10-27, branch `feat/artifacts-plan`): every action kind has `spec` and
    `observe`; a proposal stores its plan (`spec.changes`, `spec.basis`) in `verification` v2; an
    approval writes an `outcome` (`matches_spec`, `differs`) and a mismatch is audited
    (`agent_action.mismatch`); a plan that cannot be prepared refuses the proposal. Tests (run
    2026-10-27/28): 40 new (20 pure, 20 against the database); the full backend run took 15h08
    because the PC slept: 2428 passed, 2 failed (the reminders test, time-dependent, and an RLS
    knowledge test) - both passed when re-run alone; ruff, mypy, import-linter clean. VA2-VA4 not
    started. See `docs/approvals.md`.
  - VA2 (2026-10-29, branch `feat/artifacts-defences`): what the website chat stores (name, location, notes) is cleaned
    at the door (links, images, hidden text, markup out; an instruction is kept but reported; a name that is a link is refused)
    and the lead gets a note "Some text from the website chat was cleaned" naming only the kinds of finding; answers from
    the three assistants lose images and links to other sites (links inside the CRM stay); new tests that no tool takes an
    identity argument and no tool fetches an address. Tests (run 2026-10-29): 80 new/targeted passed; related suites 68 + 164
    passed (4 opt-in skipped); ruff, mypy, import-linter clean. The full backend suite was not re-run. VA3-VA4 not started.
  - VA3 (2026-10-29, branch `feat/artifacts-display`): the proposal read has `changes` and `outcome`; the approval card shows
    "Would change" and "What happened"; the web app sends `Content-Security-Policy-Report-Only`. Tests (run 2026-10-29): 6 new
    backend API tests + 19 related passed; Vitest 417 passed (11 new); lint, typecheck, production build clean; mypy and
    import-linter clean; OpenAPI refreshed. Not re-run: full backend suite, Playwright, a browser check of the card. VA4 not started.
  - VA4 (2026-10-29, branch `feat/artifacts-eval`): 7 BP-10 cases for the defences (`*-defence-*`: images and links removed from
    staff, portal and website-chat answers, an internal link kept, a link in chat notes cleaned and reported, an instruction in
    notes kept but reported, a name that is a link refused); new expectation `stored_must_contain` / `stored_must_not_contain`
    (website chat: what was stored in the lead and its timeline); `docs/injection-defences.md`. With the exit cleaning and the
    door screening switched off the new cases fail. No eval case plays an approval, so the plan/outcome mismatch is covered by
    `test_artifacts.py` only. **Phase VA (BP-29) complete.** Full backend run (2026-10-29, real PostgreSQL, 33 min, PC awake): 2530 passed, 0 failed, 4 opt-in skipped; ruff, mypy, import-linter clean. Playwright (2026-10-29, worker running, file store reachable): first full run 79 passed, 3 failed, 4 skipped - the 3 failures (documents upload, two quote journeys) were the file store being unreachable (Windows reserved TCP ports 9245-9344, so Docker could not publish 9333; the local file store now uses port 9400). Second full run in one piece: 79 passed, 3 failed, 4 skipped in 17.5 min - invoices, relationships "a customer complains" and workflow3 "manager browses" timed out under full-suite load and the three spec files re-run alone passed 14 of 14 (the last two were already known load flakes). Frontend untouched in VA4.
  - Playwright flakiness fix (2026-10-29/30, branch `fix/e2e-flaky`): `playwright.config.ts` waits 15 s per expectation and 120 s per test
    (the dev server compiles a page on first visit); `reports.spec.ts` waits for the Columns group before `.all()` (a real race);
    the `login` helper restarts a Keycloak sign-in whose password field does not appear within 20 s (3 tries); `session-refresh`
    is skipped at file level (no browser started); the report-only CSP lost `default-src 'self'` (my VA3 addition: in dev React
    evaluates strings, and each one was reported, flooding the browser console with thousands of lines). Full runs on the way: 82/1, 80/2,
    81/1, 81/1 (passed/failed, 3-4 skipped); **the last full run in one piece: 82 passed, 0 failed, 4 skipped in 25.6 min**, 0 CSP
    violations logged. One clean run does not prove the flakiness is gone.
  - Live web check of a RERA number or a company (BP-15, Phase WC, ADR 0019) - ADR accepted 2026-10-30 with the recommended answers
    (fake source first, no model reads pages in v1, every staff member who can read the record may ask 10 per hour, switch in the agent
    registry, evidence kept 12 months). WC1 (2026-10-30, branch `feat/webfetch`): `app/core/webfetch.py`, the only code that fetches a page
    for a user - https and port 443 only, only the source's host (nobody gives an address), every resolved address must be public and the
    connection is pinned to it, robots.txt honoured, redirects only inside the host and re-checked, 10 s total / 1 MB / no cookies / no
    compressed bodies, text content types only, per-host rate limiter with a daily ceiling; a guard test fails when a new module imports an
    HTTP client. Nothing calls it yet (WC2). Tests (run 2026-10-30): 119 new (pure with a fake network + the real transport against a local
    TLS server); breaking any of 9 protections makes tests fail; ruff, mypy, import-linter clean; full backend run (2026-10-30, real PostgreSQL, 28 min): 2649 passed, 0 failed, 4 opt-in skipped. WC2a (2026-10-30, branch `feat/webcheck`): `app/modules/webcheck/` pure part, no database - `rules.py` (the record a parser makes, text cleaned with
    `screen()`, caps), `sources.py` (catalogue of DEMO sources `demo_rera` and `demo_company`, each names one host and builds its own address; queries must match a
    pattern - no link, space, line break or hidden character in a RERA number; deterministic parsers: found / not_found / unclear, never a guess, unknown status or
    repeated field or wrong registration = unclear, text cleaned, excerpt built from parsed fields only, scripts/styles ignored, long lists not walked),
    `fake.py` (an in-process demo registry: the real fetcher and parser run, only the network is replaced; a poisoned page, a changed layout, a wrong registration).
    Tests (run 2026-10-30): 95 new pure tests; 14 deliberate breaks of the parsers/cleaning are all caught (3 weak tests were found and strengthened first);
    the webfetch + webcheck tests together 214 passed; ruff, mypy, import-linter clean. The full backend suite was not re-run (only new files). WC2b (2026-10-30, branch `feat/webcheck-store`): migration 0045 `web_evidence` (forced RLS, insert-only: a trigger refuses every UPDATE and refuses to delete a row
    younger than 365 days, and the app role has no UPDATE/TRUNCATE - two locks), permissions `webcheck:run` / `webcheck:read` (sales roles and support agents; the record-level rule
    decides: support may check an account, not a lead), settings `CRM_WEBCHECK_DISABLED`, `CRM_WEBCHECK_SOURCES`, `CRM_WEBCHECK_DEMO` (refused in production),
    `CRM_WEBCHECK_PER_USER_HOUR` (10), `CRM_WEBCHECK_PER_TENANT_DAY` (200); service `request_check` (permission, a record the person may read - else 404, a source that
    is switched on, a query in shape, the limits counted from queued jobs, then ONE job with ids and keys and an audit entry `webcheck.requested`), worker job `webcheck.run`
    (real fetcher + parser, demo registry for demo sources, safe to run twice, temporary failures retried up to 3 tries and only the last stored as an error), `list_evidence`
    (newest first), retention sweep in the worker's schedule. No endpoints, no notification yet (WC2c: API; the event/notification with WC4). Tests (run 2026-10-30): 60 new
    database tests (request rules, record-level denial, tenant isolation, ID tampering, limits, the job, the insert-only table, retention, the real worker); 13 deliberate breaks of
    the service and 2 of the worker wiring are all caught; ruff, mypy, import-linter, RLS guard and config tests clean; full backend run (2026-10-30, real PostgreSQL, 33 min): 2804 passed, 0 failed, 4 opt-in skipped. WC2c + notification + WC4 screens (2026-10-30, branch `feat/webcheck-api`, stacked on WC2b): API `GET /webcheck/sources`, `POST /webcheck/checks` (202, strict body: only target,
    source, query - no tenant/person/address), `GET /webcheck/evidence` (record-level 404, evidence without the hash or tenant); event `webcheck.completed` (ids and verdict code only)
    published when the evidence is stored, notification to the person who asked ("Web check finished for <name>: found / not found / could not be read with certainty / could not
    be checked"), only if they can still read the lead or account; screens: a "Web check" card on lead and account pages (form + evidence list, plain text, cleaned-text note,
    the page is not linked), Server Action that sends only source and query, `docs/webcheck.md`, Playwright `e2e/webcheck.spec.ts`; dev database at 0045. Tests (run 2026-10-30): 48
    API/notification tests; 24 + Vitest 441 passed; 10 breaks of the API/notification code caught (one survived at first: an account notification without the may-read check
    made the event job fail and retry instead of finishing - test strengthened); typecheck, lint, production build clean; full backend run (2026-10-30, real PostgreSQL, 39 min, before a one-line change to the order of the sources): 2852 passed, 0 failed, 4 opt-in skipped; after that change the web check backend files re-run: 323 passed (the RLS guard file, 6 tests, passed on its own - run in one command line with other files it lost its database fixtures, an artifact of the command, not of the code). A real-browser run found one real fault: sources were listed alphabetically, so the form started on "Company name" - RERA sources now come first (test added). Playwright: `webcheck.spec.ts` 5 passed; full suite with the demo on: 82 passed, 5 failed, 4 skipped - the 4 web check failures were the shared test agent hitting the real limit of 10 checks per hour after repeated runs, and the e-mail journey raced a standing worker it assumes is not running (both are test-environment effects; communications + webcheck specs re-run with `CRM_WEBCHECK_PER_USER_HOUR=1000` and no standing worker: 7 passed). The whole suite was not re-run in one piece after that. WC3 not started.
  - SN4 (2026-10-27, branch `feat/sentinel-eval`): 11 BP-10 cases for the Sentinel (9 staff, 1
    portal, 1 website chat; 53 agent cases in all, all `live: false`): a link, an instruction or an
    address in what a model writes is refused; a duplicate is refused; a warned proposal is stored
    with its warning (new `expect.safety_warnings`, checked on the stored proposals); a lead whose
    own text tries to steer an AI (`{{lead.poisoned}}`) warns, or blocks when the reason repeats it;
    a hidden instruction is refused before any model in all three entrances; invisible characters
    in an ordinary question are cleaned. Fixed on the way: governance cases failed on the
    development data once a real `agent_settings` row existed (version conflict) - they now change
    the settings from where they are. Docs `docs/sentinel.md`, `docs/agent-evals.md` 6g.
    **Phase SN (BP-21) complete.** Tests (run 2026-10-27): evaluation DB tests (staff, portal,
    website chat, CLI) 92 passed; with the Sentinel off the five "blocked" cases fail; the pure
    tests of the new format and dataset 47 passed; the scripted run on the development data
    passed all 4 suites; ruff, mypy, import-linter clean. The full backend suite was not re-run
    (only the harness, the dataset and one constant changed since the last full run).
- **Next planned, in order (owner, 2026-10-25):** BP-10 (design waiting for review), BP-11 (rest of
  AI Track A1), then AI Track A2 starting with BP-14 (agent registry, budgets, kill switch; needs
  an ADR), A3, A4, Marketing (Phase 16), Integrations (Phase 19). Teams come before the features
  that need them and need an ADR.
