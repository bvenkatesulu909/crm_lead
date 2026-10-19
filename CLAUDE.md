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
6. **No cloud deployment** of any kind. Everything runs locally.
7. **Commands for the user use Windows CMD syntax** (e.g. `copy`, `set`, `^` for line continuation, `.venv\Scripts\activate`). Do not give PowerShell- or bash-only commands to the user.
8. Keep `architecture.md`, `implementation-plan.md` and this file up to date when decisions change.

## Security rules (non-negotiable)

- **Tenant isolation:** every tenant-owned table has `tenant_id`; every query goes through a tenant-scoped repository; PostgreSQL RLS is enabled. `tenant_id` comes **only** from the verified token.
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
| Seed local test data (fictional) | `python -m scripts.seed_dev_data` (in `backend`, venv active) | Phase 4 |
| Keycloak admin console | http://localhost:8080/admin (credentials in `infrastructure\.env`) | Phase 4 |
| Local e-mail inbox (Mailpit) | http://localhost:8025 — invitations, verification, password reset | ADR 0004 |
| Run background worker (own CMD window) | `python -m app.worker` (in `backend`, venv active); `--once` runs due jobs and exits | ADR 0005 |
| File store (SeaweedFS, S3 API) | `127.0.0.1:8333`, keys in `infrastructure\.env`; started by `docker compose up -d` | ADR 0005 |
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
- **Pending:**
  - Assistant live check against real Claude. Blocked by Anthropic billing ("credit balance too
    low"); test with `python -m scripts.check_anthropic`.
  - Teams, RLS, e-mail task reminders via the worker (rest of Phase C).
  - Modules not started: marketing, report builder/exports, workflows, communication center, integrations, staff assistant.
- **Current phase:** Phase 18 part 2 (reports) done, waiting for the owner's review. Next planned modules: Communication Center, Marketing (Phase 16), Integrations (Phase 19), staff AI assistant (Phase 20). Next planned modules, one phase at a time: Workflow & Notifications (Phase 17, uses the worker), Reports & exports (Phase 18 part 2), Communication Center, Marketing (Phase 16), Integrations (Phase 19), staff AI assistant (Phase 20). The first Git commit still waits for the Git identity. Phase A's first Git commit is
  still open. Next proposed: Phase C (outbox + worker for e-mail reminders, teams, RLS, MinIO;
  ADR needed), then contracts and renewals.
