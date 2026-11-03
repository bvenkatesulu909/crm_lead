# ADR 0021 — One-host deployment: API, worker, database and sign-in on one server

- **Status:** Accepted (2026-11-03) with the recommended answers to the questions in section 6. OH0 (this note) is done; nothing else is built yet.
- **Date:** 2026-11-03
- **Deciders:** Project owner
- **Amends:** ADR 0007 (online deployment). It takes the alternative that ADR 0007 listed - "everything
  on one rented server with docker compose" - for the API side only. The Netlify web app, the
  production Keycloak realm, the hardening checklist and rule 6 of CLAUDE.md stay as ADR 0007 says.
- **Ticket:** CRM-112 ("API + PostgreSQL with pgvector on one host; the owner only provides the
  hosting account"). The ticket names migration 0044; the schema is at 0048 now, so every check below
  asks for "the latest migration", never a number.

## 1. Context

ADR 0007 spread the CRM over seven providers (Netlify, an API host, a worker host, a managed
database, a Keycloak host, a bucket and an SMTP service). That is flexible but expensive and a lot to
set up for one person. The owner asked for the smaller shape: **one rented server** that runs the API,
the worker and PostgreSQL (with pgvector), so that the only thing the owner has to supply is the
hosting account (and a domain name).

Today the pieces exist but only for a developer's PC: `backend/Dockerfile` (API and worker, built and
tested), `infrastructure/postgres/Dockerfile` (PostgreSQL 16 + pgvector 0.8.7), the role/database init
scripts (they create `crm_test` and use development passwords), and a production Keycloak image with a
realm that has no users. What is missing is the **assembly**: one compose file for a real server, HTTPS,
secrets that are not development values, backups that were really restored, and a way to update.

## 2. Decision (proposed)

One Linux server (any provider; Ubuntu LTS, Docker) runs this, defined in a new folder
`deploy/one-host/`:

```
 Browser ──HTTPS──► Netlify (web app, unchanged)           Browser ──HTTPS──► login.example.com
                     │ server-side calls                                          │
                     ▼                                                            ▼
              api.example.com ───────────────► [ Caddy: ports 80/443, automatic HTTPS ]
                                                    │                 │
                                                  api ◄── worker    keycloak
                                                    │                 │
                                                    └──► postgres (pgvector) ◄────┘   (no published port)
   backup job ── nightly dump of both databases ──► private S3 bucket (off the server)
```

| Piece | What | Notes |
|---|---|---|
| `caddy` | Reverse proxy, the **only** service with published ports (80, 443) | Gets and renews the HTTPS certificates itself; adds security headers |
| `postgres` | Our PostgreSQL 16 + pgvector image | Reachable only inside the compose network; two databases (`crm`, `keycloak`); no `crm_test`; the app role can never bypass row-level security |
| `migrate` | One-shot job: `alembic upgrade head` as the schema owner | Runs before `api` and `worker` start, on every update; stops the update if it fails |
| `api`, `worker` | `backend/Dockerfile`, two commands | The restricted app role only; `CRM_ENVIRONMENT=production`; resource limits |
| `keycloak` | `Dockerfile.production` + the realm without users | Own database in the same PostgreSQL; production mode behind Caddy |
| `backup` | Nightly `pg_dump` of both databases, kept 14 days on disk and copied to the bucket | Encrypted before it leaves the server (key held by the owner) |

**Deliberately unchanged from ADR 0007:** the web app stays on Netlify; files stay in an S3-compatible
bucket and mail stays with an SMTP provider (so a full disk or a lost server does not lose uploaded
documents, and mail keeps good sender reputation); nothing goes online before the hardening checklist
is ticked and the owner says "go live".

### Security rules of this layout

- Only ports 22 (SSH, keys only), 80 and 443 are open. PostgreSQL, Keycloak, the API and the worker
  are never published to the server's network.
- **No development value anywhere.** `deploy/one-host/make-env` writes a new `.env` on the server
  with random secrets; `check-env` refuses a file that has a placeholder, a short secret, a
  development password from this repository, or `CRM_ENVIRONMENT` other than `production`. Secrets are
  never in the repository, never in compose files, never in a chat.
- Containers run as non-root, with memory limits, `restart: unless-stopped`, health checks and log
  rotation (so logs cannot fill the disk).
- Images are pinned to versions; the update script builds from a tagged commit.
- Updates: `update` pulls the tagged code, builds, runs `migrate`, then restarts `api` and `worker`.
  There is no automatic database downgrade: **rollback = previous image + restore from backup** (a
  migration is never edited once applied - CLAUDE.md).
- Backups are only counted when **restored**: `restore-test` loads the latest dump into a scratch
  database, checks that the migration is at the latest revision, that row-level security is on for
  every tenant table (the existing `rls_audit`), and that pgvector works - then drops the scratch
  database. This is a line of the hardening checklist.

## 3. What this does NOT do

- It does not create the server, buy the domain, set DNS, or put anything online. **You** do that (the
  "V only" part of the ticket) and run the commands I give you over SSH. I never log in to your
  server or see its secrets.
- It does not move files or mail onto the server, and it does not host the web app.
- No Prometheus/Grafana on the server by default (they need memory a small server lacks); the API's
  token-guarded `/metrics` and the dashboards stay available for later. A free external uptime check on
  `https://api.example.com/api/v1/health` is advised.
- No high availability: one server is one failure domain. The backups are the safety net.

## 4. Sizing and cost (honest)

Minimum **2 vCPU, 4 GB RAM, 40 GB disk**: Keycloak alone wants about 1 GB, PostgreSQL and the API each a
few hundred, and the knowledge search downloads and runs two local models (embedder and reranker). 8 GB
is more comfortable if the knowledge base is used a lot. A server of that size usually costs a few to
about twenty dollars a month depending on the provider; check the provider's price page. Add the
domain, the bucket and the SMTP provider (all small), and Netlify.

## 5. Consequences

- New folder `deploy/one-host/` (compose file, Caddyfile, production database init, scripts, `.env`
  template, README), tests that read these files (no published database port, no development password,
  pinned images, every service has a health check), and a **local rehearsal** on the owner's PC with
  Docker Desktop (same files, a throwaway local certificate, no internet) that is the smoke test.
- `docs/deployment.md` gets a second path ("one server") next to the managed-services path, and its
  checklist gains the backup-restore and firewall lines. CLAUDE.md gets a command row.
- Commands for the **server** are Linux (bash) because the server is Linux. This is the one place where
  the "Windows CMD" rule cannot apply; the README says so and the commands for your PC stay CMD.

## 6. Questions for the owner - answered 2026-11-03: all as recommended

1. **Keycloak on the same server** (own database)? *Recommended: yes* - otherwise you need a second host
   just for sign-in. The alternative is a managed identity provider, which means changing the login code.
2. **Files and mail stay outside** the server (S3-compatible bucket, SMTP provider), as in ADR 0007?
   *Recommended: yes.*
3. **Caddy** as the reverse proxy (HTTPS certificates are automatic) rather than nginx + certbot?
   *Recommended: yes - fewer moving parts for a beginner.*
4. **Backups:** nightly dump, 14 days on the server and a copy in a private bucket, encrypted with a key
   only you hold? *Recommended: yes.*
5. **The web app stays on Netlify**? *Recommended: yes* (it is working and tested there). Running it on the
   same server too is possible later but is a separate decision.

## 7. Steps (each stops for review, tests first)

| Step | Content |
|---|---|
| OH0 | This ADR (documents only) |
| OH1 | `deploy/one-host/`: compose file, Caddyfile, production database init (roles, `crm` + `keycloak`, pgvector), `.env` template, `make-env` and `check-env`; tests on the files; the stack starts locally and `/api/v1/health` answers |
| OH2 | Backup, `restore-test` and `update` scripts; a restore really performed on this PC and checked |
| OH3 | The local rehearsal as a smoke test (HTTPS through Caddy, sign-in page, a protected endpoint answers 401, the worker beats, the latest migration is applied, row-level security audit clean) and the server hardening guide (firewall, SSH keys, updates) |
| OH4 | Docs: `docs/deployment.md` second path, checklist, README of the folder, CLAUDE.md; full runs |
