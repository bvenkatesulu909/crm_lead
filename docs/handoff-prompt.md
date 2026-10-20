# Handoff prompt for a new AI coding assistant (DeepSeek or any other)

Copy everything between the two lines into the first message of the new assistant. It contains no
secrets. Never paste API keys, passwords or tokens into the chat: the new assistant must read them
from environment variables and `.env` files that stay on your computer.

---

You are continuing an existing project, **crm-lead**, in `E:\crm-lead` (Windows, Docker Desktop).
Do not start from scratch and do not restructure the project. Preserve working code.

## 1. First, read these files (in this order) before changing anything
1. `CLAUDE.md` - the project rules, security rules, commands and the "Current status" list. It is the
   source of truth. Treat its rules as your own instructions even though you are not Claude.
2. `architecture.md` and `implementation-plan.md` - the design and the phases.
3. `docs/gap-analysis.md` - what is done and what is still missing.
4. `docs/deployment.md` and `docs/adr/0007-online-deployment.md` - the online deployment plan.
5. `docs/frontend.md`, `docs/auth.md`, and the doc of the module you work on (`docs/*.md`).
6. `frontend/AGENTS.md` - this Next.js version (16) differs from older versions: read
   `frontend/node_modules/next/dist/docs/` before using a Next.js API.

## 2. What the project is
A multi-tenant CRM built as a modular monolith.
- Backend: Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL (`backend/`).
- Frontend: Next.js 16, React 19, TypeScript, Tailwind 4 (`frontend/`).
- Sign-in: Keycloak (OIDC). Files: SeaweedFS (S3). Mail in development: Mailpit.
- Tests: pytest (real PostgreSQL database `crm_test`), Vitest, Playwright.
- Migrations are at 0001-0019. Never edit an applied migration; add a new one.

## 3. Working rules (must follow)
1. One phase or step at a time. Stop after it and wait for my approval.
2. Small, reviewable changes. Never generate large parts of the CRM at once.
3. Explain every step in beginner-friendly language: what a file is for, why a library is needed,
   what a command does. I am learning.
4. Ask before anything destructive (deleting files, volumes or databases, `docker compose down -v`,
   `git reset --hard`, force-push, dropping tables, rewriting applied migrations) and before major
   architectural changes (anything marked ADR).
5. Never say tests passed unless you ran them in this session and saw success. If you did not run
   them, say so. If a test fails, show the output.
6. Commit and push only when I ask.
7. Commands you give me must be Windows CMD syntax (`copy`, `set`, `^` for line continuation,
   `.venv\Scripts\activate`), not PowerShell or bash.
8. Keep `CLAUDE.md`, `architecture.md` and `implementation-plan.md` up to date when decisions change.
9. Do not invent API endpoints and do not silently replace real data with mock data.
10. I create cloud accounts, add payment methods and paste secrets myself. You never do that, and
    you never use or repeat a key that was pasted in a chat.

## 4. Security rules (non-negotiable)
- Tenant isolation: every tenant table has `tenant_id`; every query goes through the tenant-scoped
  repository; `tenant_id` comes only from the verified token.
- Never trust IDs sent by the browser. Load records through the scoped repository and policy; return
  404 if missing or not allowed.
- Every non-public endpoint needs an RBAC permission and a record-level policy. Lists are filtered
  in SQL.
- Portal (customer) users only see records of their own customer accounts.
- No secrets in code, tests, fixtures or docs. Settings come from environment variables and are
  documented with placeholders in `.env.example`.
- Server-controlled fields (tenant, creator, totals, statuses, invoice numbers) are never accepted
  from the client.
- Money uses `Decimal` / `NUMERIC`, never `float`. No string-built SQL. No tokens or passwords in logs.

## 5. Architecture rules
- Backend modules: `backend/app/modules/<module>/` with `router.py`, `schemas.py`, `models.py`,
  `repository.py`, `service.py`, `policies.py`, `api.py` (and `rules.py`). A module may import only
  `app.core` and other modules' `api.py` (checked by `lint-imports`).
- Services do not commit; the router commits once. Sensitive changes call `record_audit()`.
- Business errors are `DomainError` subclasses with a stable `code`.
- Cross-module effects go through the other module's `api.py` or a domain event
  (`app/core/events.py`); background jobs use the outbox and the worker (`python -m app.worker`).
- Frontend: load data in Server Components with `apiFetch`, change data with Server Actions. The
  browser never receives tokens. UI permission checks are for display only.

## 6. Commands (run from Windows CMD in `E:\crm-lead`)
- Start services: `cd infrastructure && docker compose up -d`
- Backend venv: `cd backend && .venv\Scripts\activate`
- Run API: `uvicorn app.main:create_app --factory --reload` (in `backend`, venv active)
- Run worker: `python -m app.worker` (in `backend`, venv active)
- Backend checks: `pytest` and `ruff check . && ruff format --check . && mypy app tests` and
  `lint-imports`
- Migrations: `alembic upgrade head`
- Web: `cd frontend && npm run dev` (http://localhost:3000)
- Web checks: `npm run lint && npm run typecheck && npm test`
- End-to-end tests: `npm run test:e2e` (needs the Docker services; the test password is in
  `frontend/.env.local`, never print it)
- Production build: `npm run build` (stop `npm run dev` first)

## 7. Current state (20 October 2026)
- Done and tested locally: login, dashboards, leads, accounts, contacts, pipeline, tasks,
  quotes with approval and PDF and e-mail, orders, invoices, support tickets, customer portal,
  documents, notifications, automation rules, reports with CSV and a report builder, user
  onboarding, AI assistant chat (live Claude check blocked by Anthropic billing).
- Last recorded test runs: backend 987 passed; Vitest 205 passed; Playwright 67 passed with a few
  known failures (the live assistant test, and slow tests under load). The full suite has not been
  re-run end to end after the latest changes.
- GitHub: `https://github.com/bvenkatesulu909/crm_lead.git`, branch `main`, latest pushed commit
  `07f7fa0`. New PDFs under `docs/` are not committed.
- Online deployment: prepared only (ADR 0007, step D1): `netlify.toml`, `backend/Dockerfile`,
  production Keycloak image and realm. Nothing is hosted. The Netlify site built successfully but
  shows "Page not found" (404). The likely cause was a forced publish folder in `netlify.toml`
  (removed in `07f7fa0`); this is not yet confirmed. The site also cannot work until the API,
  Keycloak, PostgreSQL, file bucket, SMTP and the six Netlify variables exist.
- Known issues: the tenant filter in workflow rules is not covered by a failing test (a mutation
  was not caught); row-level security (Phase C) is not finished; the first Git history still has an
  old private network address in one commit (not rewritten).

## 8. What I want next (confirm the first item with me before starting)
1. Help me finish the Netlify deploy: check the build settings and the deploy log, and tell me
   exactly what I must click or provide. You do not enter secrets or create accounts for me.
2. Then follow `docs/deployment.md` step D2 with me, one service at a time: database, API,
   Keycloak, worker, file bucket, mail, domain, Netlify variables.
3. Then the remaining planned modules, one phase at a time, each with tests and a doc:
   Communication Center, Marketing (Phase 16), Integrations (Phase 19), staff AI assistant
   (Phase 20), contracts and renewals, row-level security and teams (rest of Phase C).
4. Before anything goes online with real data: the hardening checklist in `docs/deployment.md`
   (new secrets, revoke the old Anthropic key, backups, upload size limits, security headers).

## 9. How to answer me
- Start by saying which files you read and what you understood the current state to be.
- Propose a short plan for the first step and wait for my "go".
- After each step: what changed, which files, which checks you really ran and their real results,
  what is not done, and the exact next step.

---
