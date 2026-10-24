# crm-lead — Architecture

> Status: **Living design document** (updated 2026-10-20). It describes the intended design;
> what is implemented, and what is still missing, is tracked in
> [implementation-plan.md](implementation-plan.md) and [docs/gap-analysis.md](docs/gap-analysis.md).
> Changes to the decisions marked **[ADR]** are *major architectural changes* and need explicit approval.

---

## 1. Goals and non-goals

**Goals**

- A production-oriented CRM that runs entirely on a local Windows machine (Docker Desktop for infrastructure).
- Secure by default: every request is authenticated, every record access is authorized, tenants are isolated.
- Built incrementally, one module at a time, each with automated tests and database migrations.
- Easy to understand for a developer who is still learning: boring, well-known technology and clear boundaries.

**Non-goals (for now)**

- No cloud deployment, no Kubernetes, no microservices.
- No multi-region, no horizontal scaling work until a real need appears.

---

## 2. Technology stack and why each piece is there

| Layer | Technology | Why it is needed |
|---|---|---|
| Web UI | **Next.js** (App Router) + **React** | React builds the UI from components; Next.js adds routing, server-side rendering and a server layer we use to hold login sessions securely. |
| Language (UI) | **TypeScript** | Catches type mistakes at compile time instead of in the browser. |
| Styling | **Tailwind CSS** | Utility classes keep styling consistent without writing large CSS files. |
| API | **Python 3.12** + **FastAPI** | FastAPI is fast, typed (via Pydantic) and generates OpenAPI docs automatically. |
| Validation | **Pydantic v2** | Validates every request/response body; comes with FastAPI. |
| Configuration | **pydantic-settings** | Reads configuration from environment variables / `.env` with type checking. |
| Database | **PostgreSQL 16** | Reliable relational database; supports Row-Level Security, JSONB, full-text search. |
| ORM | **SQLAlchemy 2.x** | Maps Python classes to tables and builds safe (parameterised) SQL. |
| DB driver | **psycopg 3** | The PostgreSQL driver SQLAlchemy uses to talk to the database. |
| Migrations | **Alembic** | Versioned, reviewable database schema changes. Never edit tables by hand. |
| Identity | **Keycloak** (OIDC) | Handles login, passwords, MFA, sessions and issues signed tokens. We never store passwords ourselves. |
| UI auth library | **openid-client** + **jose** | Certified OIDC client runs the login (code + PKCE) on the Next.js server; jose encrypts the session cookie. Chosen over Auth.js: small, explicit, fully tested (see docs/frontend.md). |
| API token checks | **PyJWT** (+ `cryptography`) | Verifies the signature and claims of Keycloak access tokens using Keycloak's public keys (JWKS). |
| Files | **SeaweedFS** (S3-compatible, local; ADR 0005 - replaced MinIO, whose images are no longer published) | Stores generated PDFs and, later, uploaded documents outside the database. Same S3 API as MinIO/AWS S3, behind `app/core/storage.py`. |
| Email (dev) | **Mailpit** | Catches all outgoing email locally so nothing is sent to real people during development. |
| Background jobs | PostgreSQL-backed job table + worker process | Workflow automation, emails and integrations run outside the HTTP request. No extra broker needed at first. |
| Backend tests | **pytest**, **httpx**, `pytest-cov` | Unit and API tests against a real PostgreSQL test database. |
| E2E tests | **Playwright** | Drives a real browser through login and key user journeys. |
| Python tooling | **uv**, **ruff**, **mypy** | uv = fast dependency/virtualenv manager with a lock file; ruff = linter/formatter; mypy = static type checker. |
| JS tooling | **npm**, **ESLint**, **Prettier** | Package manager, linter and formatter for the frontend. |
| Boundary checks | **import-linter** | Fails the build if one backend module imports another module's internals. |
| Containers | **Docker Desktop** + Docker Compose | Runs PostgreSQL, Keycloak, SeaweedFS and Mailpit locally with one command. |
| Version control | **Git** | History, branches, code review. |

---

## 3. System overview

```
                  ┌──────────────────────────── Browser ────────────────────────────┐
                  │  Staff CRM UI (/app/*)        Customer Portal UI (/portal/*)    │
                  └───────────────┬─────────────────────────────────────────────────┘
                                  │ HTTPS (session cookie, httpOnly)
                                  ▼
              ┌─────────────────────────────────────────┐        OIDC login
              │  Next.js server  (frontend/)            │◄──────────────────────┐
              │  - renders pages                        │                       │
              │  - encrypted session holds tokens       │                       │
              │  - forwards calls with Bearer token     │                       │
              └───────────────┬─────────────────────────┘                       │
                              │ HTTP + Authorization: Bearer <access token>     │
                              ▼                                                 │
              ┌─────────────────────────────────────────┐   JWKS (public keys) ┌┴───────────┐
              │  FastAPI modular monolith (backend/)    │─────────────────────►│  Keycloak  │
              │  core: config, db, auth, tenancy, authz │                      └────────────┘
              │  modules: accounts, leads, sales, ...   │
              │  worker: background jobs (same code)    │
              └───────┬───────────────┬─────────────────┘
                      │ SQL           │ S3 API            SMTP
                      ▼               ▼                     ▼
               ┌────────────┐   ┌───────────┐        ┌───────────┐
               │ PostgreSQL │   │ SeaweedFS │        │  Mailpit  │
               └────────────┘   └───────────┘        └───────────┘
```

**Key point – Backend-for-Frontend (BFF):** the browser never sees access tokens. The Next.js server keeps
them in an encrypted, httpOnly session and attaches them when it calls the API. This protects tokens
from JavaScript-based attacks (XSS).

---

## 4. Modular monolith **[ADR]**

One deployable backend (`backend/`) split into **modules** with strict boundaries. Later, a module
could be extracted into its own service without rewriting it.

### 4.1 Module list

| # | Module (package name) | Owns (examples) |
|---|---|---|
| 1 | `identity` – User & Role Management | tenants, users (profile mirror of Keycloak), roles, teams, permissions |
| 2 | `accounts` – Customer Accounts | customer accounts, account hierarchy, addresses |
| 3 | `contacts` – Contacts | contacts, contact ↔ account links |
| 4 | `leads` – Leads | leads, lead sources, lead conversion |
| 5 | `sales` – Opportunities | pipelines, stages, opportunities, forecasts |
| 6 | `activities` – Activities & Tasks | tasks, calls, meetings, notes, reminders |
| 7 | `marketing` – Marketing | campaigns, segments, consent (e-mail templates come from `communications`, ADR 0012) |
| 8 | `catalog` – Products & Quotations | products, price books, quotes, quote lines |
| 9 | `orders` – Orders | orders, order lines, fulfilment status |
| 10 | `billing` – Invoices & Payments | invoices, payments, credit notes |
| 11 | `support` – Customer Support | tickets, SLAs, comments, knowledge base |
| 12 | `portal` – Customer Portal | portal users, portal access grants, portal-facing API |
| 13 | `reporting` – Reports & Analytics | report definitions, dashboards, read-only queries |
| 14 | `workflows` – Workflow Automation | rules (trigger → condition → action), job runs |
| 15 | `documents` – Document Management | document metadata, versions, links to records; files in the S3 file store |
| 16 | `assistant` – AI Chatbot & Voice | conversations, tool definitions, provider adapters |
| 17 | `integrations` – External Integrations | connectors, webhooks (in/out), sync state |
| 18 | `communications` – Communication Center | one-to-one e-mail (sent and logged), e-mail templates, conversation history (ADR 0012) |

Shared, non-business code lives in `app/core` (config, DB session, auth, tenancy, authorization,
audit log, events, errors, pagination).

### 4.2 Inside a module

```
app/modules/leads/
├── __init__.py
├── api.py          # PUBLIC interface other modules may call (functions + DTOs only)
├── router.py       # FastAPI endpoints (HTTP layer, thin)
├── schemas.py      # Pydantic request/response models
├── models.py       # SQLAlchemy tables owned by this module
├── repository.py   # All database queries for this module (tenant-scoped)
├── service.py      # Business rules and use cases
├── policies.py     # Record-level authorization rules for this module
├── events.py       # Domain events this module publishes
└── permissions.py  # Permission strings, e.g. "lead:read", "lead:convert"
```

Request flow: `router` → `service` → (`policies` check) → `repository` → database.

### 4.3 Boundary rules

1. A module may import only another module's **`api.py`** (and `app.core`). Never its `models`, `repository` or `service`.
2. Foreign keys across modules are allowed (they protect data integrity), but cross-module **reads** go through the other module's `api.py`, not by joining its tables in your queries. (Exception: `reporting`, which uses read-only views.)
3. Modules communicate asynchronously through **domain events** (e.g. `lead.converted`) written to an outbox table in the same transaction, then dispatched by the worker.
4. These rules are enforced automatically by **import-linter** contracts in CI/tests.

---

## 5. Multi-tenancy **[ADR]**

The first release may have only one tenant, but the data model is multi-tenant from day one,
because adding tenancy later is a painful rewrite.

- **Model:** shared database, shared schema, `tenant_id UUID NOT NULL` column on every tenant-owned table.
- **Source of truth for tenant:** the authenticated identity — the CRM `users` row found by the verified token's `(iss, sub)` (ADR 0002). **Never** from a URL, header or body supplied by the client.
- **Layer 1 – application:** a `TenantScopedRepository` base class adds `WHERE tenant_id = :current_tenant` to every query and sets `tenant_id` on every insert. Raw SQL outside repositories is not allowed in modules.
- **Layer 1b – same-tenant foreign keys (implemented):** every reference between tenant-owned tables is a composite foreign key `(tenant_id, x_id) → table(tenant_id, id)`, so PostgreSQL rejects cross-tenant links even if application code has a bug.
- **Layer 2 – database (defence in depth, implemented 2026-10-23, ADR 0009):** PostgreSQL **Row-Level Security** with ENABLE + FORCE and a tenant policy on every table that has `tenant_id` (47 tables; `leads` also checks the owner scope). `crm_current_tenant()` reads `app.tenant_id`, which the API sets per transaction with `set_config(..., true)` after resolving the principal (re-applied after every commit); unset means no rows. The application and the worker connect as the non-owner `crm_app` role without BYPASSRLS; the few lookups that must run before a tenant is known (login, sign-up, worker claim, metrics counts) are narrow SECURITY DEFINER functions. A guard test fails any new tenant table without RLS.
- **Indexes and uniqueness** always include `tenant_id` first (e.g. `UNIQUE (tenant_id, email)`).
- **Tests:** every module ships a *tenant isolation test*: create data in tenant A, act as tenant B, assert 404 on read/update/delete and absence from lists/search/reports/exports.

Cross-tenant access returns **404 Not Found** (not 403), so attackers cannot discover which IDs exist.

---

## 6. Authentication (OIDC with Keycloak)

| Keycloak object | Purpose |
|---|---|
| Realm `crm` | Holds all users, clients and roles for the CRM. |
| Client `crm-web` (confidential) | Used by Next.js for the Authorization Code flow with PKCE. Client secret lives in `.env`. |
| Client `crm-api` (bearer-only / audience) | Represents the API; tokens must contain `aud = crm-api`. |
| Audience mapper on `crm-web` | Adds `crm-api` to `aud`; only the six CRM realm roles are copied into tokens. |
| Tenant / user type | **Not** in the token: looked up in the CRM `users` table by the token's verified `(iss, sub)` – see ADR 0002. |

Customer-portal users log in through the same realm and client; a separate realm is still an
option later. Full details, test identities and setup: [docs/auth.md](docs/auth.md).

**API token validation (every request, implemented):** signature against Keycloak JWKS (cached,
refreshed on key rotation), `iss`, `aud`, `exp`, `nbf`, `iat`, `typ=Bearer`, allowed algorithm
(`RS256` only) — then build a `Principal` (`user_id`, `tenant_id`, `user_type`, `roles`,
`permissions`) from the token **and the CRM database**.

Keycloak realm configuration is exported to `infrastructure/keycloak/realm-crm.json` (no real secrets) so the
setup is reproducible.

---

## 7. Authorization (RBAC + record-level) **[ADR]**

Authorization is checked **on the server, for every request, in two steps**.

### 7.1 Step 1 – RBAC (can this role do this kind of action?)

Permissions are strings `resource:action[:scope]` (`own` / `all` within the caller's tenant),
grouped into the six roles chosen by the project owner (implemented in
`backend/app/core/auth/rbac.py`; full matrix in [docs/auth.md](docs/auth.md)):

| Role | Summary |
|---|---|
| `super_admin` | Platform operator: manages tenants. **No access to tenant business data.** |
| `tenant_admin` | Everything inside one tenant, incl. user & role management |
| `sales_manager` | All sales records (accounts, contacts, leads) of the tenant |
| `sales_agent` | Only the sales records they own |
| `support_agent` | Reads all accounts and contacts of the tenant; no sales edits |
| `customer` (portal) | Only portal endpoints, only accounts in their `portal_access_grants` |

Marketing and finance roles from the first draft are dropped for now; they can be added when
those modules are built. Endpoints declare what they need:
`Depends(require_any_permission(Permission.ACCOUNT_READ_ALL, Permission.ACCOUNT_READ_OWN))`.

### 7.2 Step 2 – Record-level (can this user act on *this* record?)

Each module's `policies.py` decides using record attributes:

- **Tenant** – always (see §5).
- **Ownership** – `owner_id` = user (sales reps).
- **Team / hierarchy** – record owner is in a team the user manages.
- **Sharing** – explicit share grants (record shared with a user/team).
- **Account scope** – for portal users: record belongs to a customer account listed in their `portal_access_grants`.

Lists are filtered **in the SQL query** by the same policy (not filtered after loading), so
pagination and counts are correct and nothing leaks.

### 7.3 Never trust IDs from the frontend

- Any ID in a path or body (`account_id`, `contact_id`, `customer_id` …) is **looked up through the
  scoped repository and policy** before use. Unknown or unauthorised → 404.
- When creating a record linked to another (e.g. a contact on an account), the service verifies the
  user may access the parent record.
- Fields such as `tenant_id`, `owner_id` (for non-managers), `created_by`, totals and statuses with
  business rules are **set by the server**, not accepted from the client (separate input schemas).

---

## 8. Customer Portal

- Portal users are Keycloak users with `user_type=customer`, in the same tenant.
- The `portal` module exposes **its own API routes** (`/api/portal/v1/...`) with smaller response
  schemas (no internal notes, margins, owner info).
- A portal user may be linked to one or more customer accounts via `portal_access_grants`
  (`tenant_id, portal_user_id, account_id, scopes`). Every portal query is filtered by those grants.
- Staff endpoints reject customer tokens and portal endpoints reject staff tokens.

---

## 9. Cross-cutting concerns

| Concern | Approach |
|---|---|
| Primary keys | UUID (v7 when available, else v4) – not guessable, safe to expose. |
| Timestamps | `created_at`, `updated_at` in UTC (`timestamptz`). |
| Audit trail | `audit_log` table: who, when, tenant, action, entity, before/after diff. Written by core for every create/update/delete. |
| Soft delete | `deleted_at` for business records; hard delete only for retention/GDPR jobs. |
| Concurrency | `version` column → optimistic locking; client sends it back on update, mismatch → 409. |
| Money | `NUMERIC(18,4)` + ISO currency code; never floats. |
| Errors | Standard JSON problem format (`type`, `title`, `status`, `detail`, `trace_id`). No stack traces to clients. |
| API versioning | URL prefix `/api/v1`, `/api/portal/v1`. |
| Pagination | Cursor or limit/offset with a max page size. |
| Logging | Structured JSON logs with `trace_id`, `tenant_id`, `user_id`; **never** tokens, passwords or full card data. |
| Rate limiting | Per user / per IP on auth-sensitive and AI endpoints. |
| Input safety | Pydantic validation, SQLAlchemy parameters (no string-built SQL), file type/size checks on uploads. |
| CORS / CSRF | API only accepts calls from the Next.js server origin; Next.js uses SameSite=Lax cookies, OIDC `state`, and Server Actions' built-in Origin check. |

---

## 10. Configuration and secrets

- All configuration comes from **environment variables**, read by `pydantic-settings` (API) and Next.js env (web).
- `.env.example` files are committed and contain **placeholder** values and comments only.
- Real `.env` files are git-ignored. Docker Compose reads `infrastructure/.env`.
- No secrets, passwords or API keys in source code, test fixtures, Keycloak exports or documentation.
- The app fails fast at startup if a required variable is missing.

---

## 11. Background work, events and workflows

- **Outbox pattern:** a service writes its change *and* an `outbox_jobs` row in one transaction (`app/core/outbox.py`, ADR 0005; built in Phase C1).
- **Worker** (`python -m app.worker`, same codebase) picks jobs with `SELECT … FOR UPDATE SKIP LOCKED`, dispatches events to subscribers (other modules, workflow engine, webhooks), retries with backoff, and moves permanently failed jobs to a dead-letter state.
- **Workflow automation** = tenant-defined rules: *trigger* (event or schedule) → *conditions* → *actions* (create task, send email, update field, call webhook). Actions run with the permissions of a designated automation user, never above the tenant.
- If load later demands it, the job table can be swapped for Redis/RabbitMQ behind the same interface.

---

## 12. Documents

- Metadata (name, type, size, checksum, owner, linked record) in PostgreSQL; bytes in the S3 file store (SeaweedFS) under
  `tenant/{tenant_id}/…` keys.
- Upload/download go through the API (or short-lived pre-signed URLs issued **after** an authorization check).
- Allowed file types and maximum size are configurable; filenames are sanitised.

---

## 13. AI chatbot and voice assistant

- The `assistant` module talks to an LLM through a **provider adapter** (provider chosen later; API key via env var).
- The assistant can only act through **tools** that call the same module `api.py` functions **as the
  current user** — so RBAC, record-level and tenant checks apply exactly as in the UI.
- Write actions proposed by the assistant require user confirmation in the UI.
- Prompt-injection defence: data read from records is treated as data, never as instructions; tool
  results are size-limited; conversations are tenant-scoped and audited.
- Voice: browser speech-to-text / text-to-speech first (Web Speech API), server-side STT/TTS provider later behind an adapter.

---

## 14. External integrations

- Each integration is an **adapter** in `integrations/connectors/<name>` implementing a common interface.
- Outgoing webhooks are signed (HMAC-SHA256 with a per-subscription secret) and delivered by the worker with retries.
- Incoming webhooks verify signatures and are idempotent (event IDs stored).
- Credentials per tenant are stored encrypted in the database (key from env var), never logged.

---

## 15. Testing strategy

| Level | Tool | What it covers |
|---|---|---|
| Unit | pytest | Services and policies with fakes. |
| Integration / API | pytest + httpx + real PostgreSQL (test database in Docker) | Endpoints, repositories, migrations, RLS. Tokens are signed by a test key so tests don't need Keycloak running. |
| Security | pytest | Mandatory per module: tenant isolation, role denial, record-level denial, ID tampering. |
| Architecture | import-linter | Module boundaries. |
| Migrations | pytest | `alembic upgrade head` then `downgrade` on an empty DB. |
| End-to-end | Playwright | Real browser + real Keycloak: login, key journeys per module, portal isolation. |
| Static | ruff, mypy, ESLint, `tsc --noEmit` | Style and type errors. |

---

## 16. Proposed folder structure

```
crm-lead/
├── CLAUDE.md                     # Project rules for Claude Code / contributors
├── README.md                     # How to set up and run (created in Phase 0)
├── architecture.md               # This document
├── implementation-plan.md        # Phases + acceptance criteria
├── .gitignore
├── .editorconfig                 # Consistent line endings/indentation across editors
├── .gitattributes                # Normalise line endings (important on Windows)
│
├── docs/
│   ├── adr/                      # Architecture Decision Records (one file per decision)
│   └── modules/                  # Short design note per CRM module
│
├── infrastructure/
│   ├── docker-compose.yml        # PostgreSQL, Keycloak, SeaweedFS (files), Mailpit
│   ├── .env.example              # Placeholder settings for the containers
│   ├── postgres/init/            # Shell script run on first start (creates roles + DBs)
│   └── keycloak/realm-crm.json   # Realm export (no real secrets)
│
├── backend/                      # Python / FastAPI backend
│   ├── requirements.txt          # Pinned runtime dependencies
│   ├── requirements-dev.txt      # Pinned test/lint tools (includes requirements.txt)
│   ├── pyproject.toml            # Tool config only (pytest, ruff, mypy)
│   ├── .env.example
│   ├── alembic.ini               # Alembic settings (no database URL inside)
│   ├── alembic/                  # env.py + versions/ (one file per migration)
│   ├── app/
│   │   ├── main.py               # Creates the FastAPI app, registers middleware and routers
│   │   ├── worker.py             # Background job runner (later)
│   │   ├── api/v1/               # Versioned HTTP routes (health, then module routers)
│   │   ├── model_registry.py     # Imports all module models for Alembic
│   │   ├── core/                 # config, db, models (base + mixins), logging, errors; later auth, tenancy, authz
│   │   └── modules/              # identity, accounts, contacts, leads, sales, ... (17 modules)
│   └── tests/
│       ├── conftest.py           # Shared fixtures (settings, test client; later test DB, tokens)
│       └── modules/<module>/     # Incl. test_tenant_isolation.py per module
│
├── frontend/   # (was planned as apps/web)                      # Next.js frontend
│       ├── package.json
│       ├── .env.example
│       ├── next.config.ts
│       ├── tailwind / postcss config
│       ├── src/
│       │   ├── app/
│       │   │   ├── (app)/        # Staff CRM pages  → /...
│       │   │   ├── portal/       # Customer portal → /portal/...
│       │   │   └── api/auth/     # OIDC login + callback route handlers
│       │   ├── components/       # Shared UI components
│       │   ├── lib/              # API client, auth helpers
│       │   └── features/<module>/ # UI per CRM module
│       └── e2e/                  # Playwright tests + playwright.config.ts
│
└── scripts/                      # Windows .cmd helper scripts (dev-up, test-all, ...)
```

---

## 17. Open decisions (to confirm before the relevant phase)

1. LLM provider: **decided — Anthropic Claude API; knowledge search: local embeddings + pgvector (ADR 0003; groundwork decisions in ADR 0010).** Speech provider: still open (decided in the assistant phase, after text chat).
2. Which external systems to integrate first (Phase 19) – e.g. email (IMAP/SMTP), calendar, accounting, payment provider.
3. Whether portal users get a separate Keycloak realm (stronger separation) or the same realm. **Decided for now: same realm, same client; user type comes from the CRM database.**
4. Tenant mapping — **decided (ADR 0002, accepted):** tenant comes from the CRM `users` table, looked up by the token's verified `(iss, sub)`; no tenant claim in tokens.
