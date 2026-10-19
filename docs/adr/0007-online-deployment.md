# ADR 0007 — Online deployment (Netlify for the web app, hosting for everything else)

- **Status:** Accepted (2026-10-19; hosting path: Netlify for the web app plus separate hosts for API, worker, database, Keycloak, files and mail; step D1 done - see docs/deployment.md; D2 staging and D3 go-live wait for the owner's accounts and decisions)
- **Date:** 2026-10-19
- **Deciders:** Project owner

## Context

The CRM has so far run only on the owner's computer (CLAUDE.md rule 6: "No cloud deployment of
any kind"). The owner now wants it online, starting with Netlify.

Netlify hosts **web sites and serverless functions**. The CRM is more than a web site:

| Part | What it is | Can Netlify run it? |
|---|---|---|
| Web app (`frontend/`) | Next.js 16 with server-side rendering and Server Actions | **Yes** (Netlify supports Next.js through its runtime; limits to verify below) |
| API (`backend/`) | FastAPI (Python) | **No** - needs an always-on host |
| Worker (`python -m app.worker`) | Background jobs, e-mails, schedules | **No** - a long-running process |
| PostgreSQL | The database | **No** - a managed database |
| Keycloak | Sign-in service (Java) | **No** - a container host, or another identity provider |
| File store | S3-compatible (SeaweedFS locally) | **No** - a cloud object store (the code already speaks S3) |
| Mail | SMTP (Mailpit locally) | **No** - a real mail provider |

So "deploy to Netlify" means: Netlify for the screens **plus** hosting for the other six parts.

Today's setup is **not safe to put on the internet as it is**: Keycloak runs in development mode over
HTTP, the test users share one development password, passwords and keys in `.env` files are
development values, there is no HTTPS, no backups, and the database is not row-level secured
yet (gap-analysis Phase C, RLS).

## Decisions (proposed)

1. **Lift rule 6 for this deployment only** and replace it in CLAUDE.md by: *"Cloud deployment
   only as described in ADR 0007, never with development settings or test data."*

2. **Hosting layout** (the owner picks the providers; options in the table below):

   | Part | Where | Notes |
   |---|---|---|
   | Web app | **Netlify** | Build command `npm run build`; environment variables set in Netlify, never in the repository |
   | API + worker | A container/app host (Render, Fly.io, Railway or similar) | Two services from the same code: web process (uvicorn) and worker |
   | PostgreSQL | Managed Postgres (the host's, Neon, Supabase, …) | Daily backups on; separate databases for the CRM and for Keycloak |
   | Keycloak | Container on the same host, **production mode** (`start`, HTTPS, its own database), **or** a managed identity provider | A managed provider (Auth0, Keycloak hosting) means changing the login code - to be decided |
   | Files | S3-compatible bucket (AWS S3, Cloudflare R2, Backblaze B2) | Only settings change (`CRM_FILES_S3_*`); bucket private |
   | Mail | SMTP provider (Brevo, Postmark, Amazon SES, …) | Sender domain with SPF/DKIM, so mails don't land in spam |

3. **Production hardening before anything is public** (a checklist, each item tested):
   - HTTPS everywhere (Netlify and the hosts provide certificates); `CRM_ENVIRONMENT=production`
     (the code already insists on HTTPS issuers and file stores in production).
   - **No test users and no development password.** A fresh Keycloak realm with one real
     administrator; "sign-up with approval" stays on, or is switched off.
   - All secrets freshly generated and stored only in the hosts' secret settings; the Anthropic key
     rotated (it was shown in chat earlier).
   - Row-level security (Phase C) finished, or the deployment limited to one organisation.
   - Backups of PostgreSQL **and** the file bucket, with a restore test.
   - Security response headers and rate limiting at the edge; logs without personal data.
   - The documented Phase 21 (hardening) checklist completed.

4. **Known risks to verify before building:**
   - **File uploads and PDFs:** serverless functions limit request/response sizes and run time.
     Our uploads allow up to 20 MB and go through Server Actions (Next.js default: 1 MB). Netlify's
     exact limits must be confirmed; if too small, uploads should go **directly from the browser to
     the bucket** with short-lived signed URLs, which needs a small design change.
   - **Cookies and sessions** depend on one stable domain; the web app, API and Keycloak need
     matching addresses (e.g. `app.example.com`, `api.example.com`, `login.example.com`) - a
     domain name must be bought and configured.
   - **Cost:** Netlify's current plans are credit based (a free plan with a monthly credit
     allowance that pauses the site when used up; paid plans from about $9/month), and the API
     host, database, Keycloak host, bucket and mail provider each have their own price. Expect a
     monthly cost for the whole stack; the exact amount depends on the providers chosen.
   - **Accounts:** creating the Netlify and hosting accounts, adding payment methods and entering
     secrets must be done by **you**, not by me. I prepare the configuration and instructions and
     can run commands you approve.

## Consequences

- New files: Netlify configuration (`netlify.toml`), container definitions for the API, worker and
  Keycloak, a production settings guide (`docs/deployment.md`), and a deployment checklist.
- The local setup keeps working unchanged (docker compose, `localhost`).
- The project is no longer "local only": security reviews, dependency scanning, backups and
  monitoring become ongoing responsibilities.

## Alternatives considered

- **Everything on one rented server (VPS) with docker compose** - closest to today's setup, one
  monthly price, full control; more to maintain yourself. Netlify not needed (Next.js runs there
  too). Good if the goal is simply "online".
- **Netlify for the web app only, API/DB on this PC through a tunnel** - quick demo, but the PC must
  stay on and the CRM data is exposed through the tunnel.
- **Stay local** (network mode for demos on your Wi-Fi).

## Proposed order of work (each step stops for review)

1. **D1 - Preparation (no internet):** production settings, container files, `netlify.toml`,
   checklist, a clean Keycloak realm without test users, direct-to-bucket uploads if needed.
2. **D2 - Staging:** deploy to a private test environment (behind a password), run the end-to-end
   tests against it.
3. **D3 - Go live:** domain, HTTPS, real administrator, backups verified, owner's sign-off.
