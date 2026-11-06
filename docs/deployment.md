# Deploying the CRM online (ADR 0007, ADR 0021)

**Status: prepared, not deployed.** Everything below exists and was tested on a PC. Nothing is online
yet, no accounts were created and no money was spent. Steps D2 (private staging) and D3 (go live) need
accounts and decisions that only **you** can make; this guide lists them. Rule 6 of CLAUDE.md holds:
nothing goes online until you say "go live" and the checklist at the end is ticked.

## Two ways to host it

| | **One server** (ADR 0021, CRM-112) | **Managed services** (ADR 0007) |
|---|---|---|
| What you rent | One Linux server (2 vCPU, 4 GB RAM, 40 GB disk at least) + a domain | A container host, a managed PostgreSQL, a Keycloak host, ... |
| Runs on it | Proxy with automatic HTTPS, database + pgvector, migration job, API, worker, Keycloak, nightly backup | The same parts, each on its own host |
| Web app, files, mail | Netlify, an S3 bucket, an SMTP provider (unchanged) | The same |
| You look after | The server itself (updates, firewall, disk) - [one-host-hardening.md](one-host-hardening.md) | Several bills and several dashboards |
| Backups | Built in: nightly, encrypted for a key only you hold, restore tested by a script | Whatever each host offers |
| Prepared in | [`deploy/one-host/`](../deploy/one-host/README.md) - **recommended** | `backend/Dockerfile`, `Dockerfile.production`, `netlify.toml` (this guide) |

The one-server path was built and rehearsed on a PC (the whole stack behind HTTPS with a throwaway
certificate authority, a 22-check smoke test that passes, a backup that was really encrypted, restored and
compared). **First real server: 2026-11-06** (staging, see below). The rest of this guide describes the
managed path; where the one-server path differs, `deploy/one-host/README.md` is the guide to follow.

### First real server (staging, 2026-11-06)

D2 staging runs on one Google Cloud VM (e2-medium, Ubuntu 24.04, Mumbai) with the web app on Netlify,
documents and backups in two private Google Cloud Storage buckets (S3 interoperability keys) and mail
through Brevo. What was checked on the real server:

- the stack is healthy (API, worker, Keycloak, PostgreSQL with pgvector 0.8.7, proxy, backup); the
  database is at the latest migration; `/api/v1/health/ready` answers 200 over Let's Encrypt HTTPS;
- `sudo bin/server-check.sh`: 0 FAIL, 0 WARN;
- an encrypted backup of both databases reached the backup bucket, and `bin/restore-test.sh` said
  **RESTORE TEST PASSED** with real rows (2 organisations, 1,000 accounts, 1,000 contacts, 301 leads);
- the Keycloak administration console answers 403 from outside (`ADMIN_ALLOWED_IPS=127.0.0.1`).

Found only on the real server and fixed: backups to Google Cloud Storage (AWS CLI checksums, PR #94),
the server check's reading of the finished migration job (PR #94), and creating organisations (the
API's Keycloak admin calls and the realm's robot account, PR #95). It is **staging, not "go live"**:
Netlify visitor protection is on and the rest of the checklist below is still open.

## What runs where

```
 Browser ──HTTPS──► Netlify  (web app: frontend/)
                      │  server-side calls
                      ├──────────────► API host  (backend/Dockerfile, command: uvicorn …)
 Browser ──HTTPS──► Keycloak host  (infrastructure/keycloak/Dockerfile.production)
                                       │            │
                       Worker (same image, command: python -m app.worker)
                                       ▼            ▼
                      Managed PostgreSQL     S3 bucket (files)     SMTP provider (mail)
```

| Part | Prepared file | Hosting you choose |
|---|---|---|
| Web app | `netlify.toml` | **Netlify** |
| API | `backend/Dockerfile` (default command) | Render, Fly.io, Railway or similar (container host) |
| Worker | `backend/Dockerfile`, command `python -m app.worker` | same host, a second service |
| Sign-in | `infrastructure/keycloak/Dockerfile.production` + `realm-crm-production.json` | container host, **own database** |
| Database | migrations in `backend/alembic` | managed PostgreSQL (the host's, Neon, Supabase, …) |
| Files | S3 settings `CRM_FILES_S3_*` | S3-compatible bucket (AWS S3, Cloudflare R2, Backblaze B2) |
| Mail | SMTP settings `CRM_SMTP_*` | SMTP provider (Brevo, Postmark, Amazon SES, …) |

You also need **a domain name** with three names, for example `app.example.com` (Netlify),
`api.example.com` (API) and `login.example.com` (Keycloak). HTTPS certificates come with the hosts.

## What is already done and tested (D1)

- `netlify.toml`: Netlify builds `frontend/` (`npm run build`, Node 22). The production build was run
  here and is clean (no warnings).
- `backend/Dockerfile` + `.dockerignore`: one image for API and worker, runs as a non-root user,
  contains no tests or secrets. Built and started here against a database: health OK, protected
  endpoints answer 401 without a token, the worker starts.
- **A real bug found and fixed on the way:** `requirements.txt` lacked `PyJWT` and `cryptography`,
  so a clean install (such as this image) crashed at start. A new test
  (`tests/test_requirements.py`) now fails whenever an imported library is missing there.
- `infrastructure/keycloak/Dockerfile.production` + `realm-crm-production.json` (generated by
  `python -m scripts.make_production_realm` from the development realm, kept in sync by a test):
  **no test users**, HTTPS required, self sign-up off, stronger password rule (14 characters, upper,
  lower, digit), addresses and mail settings from environment variables. Started here against a
  throwaway database: the realm imports, has 0 users, and the placeholders resolve.

## Settings per service (names only - set them in each host's secret settings)

Generate **new** random values for every secret. Never reuse a development value.

**Netlify** (Site configuration → Environment variables):
`APP_BASE_URL=https://app.example.com`, `API_BASE_URL=https://api.example.com/api/v1`,
`OIDC_ISSUER=https://login.example.com/realms/crm`, `OIDC_CLIENT_ID=crm-web`,
`OIDC_CLIENT_SECRET`, `SESSION_SECRET` (32 random bytes, base64url).
Do **not** set `E2E_USER_PASSWORD`.

**API and worker** (same settings for both):
`CRM_ENVIRONMENT=production`, `CRM_DOCS_ENABLED=false`,
`CRM_DATABASE_URL` (restricted app user), `CRM_OIDC_ISSUER=https://login.example.com/realms/crm`,
`CRM_OIDC_AUDIENCE=crm-api`, `CRM_CORS_ALLOWED_ORIGINS=https://app.example.com`,
`CRM_WEB_APP_URL=https://app.example.com`,
`CRM_KEYCLOAK_ADMIN_CLIENT_SECRET` (= Keycloak's `CRM_USER_ADMIN_CLIENT_SECRET`),
`CRM_FILES_S3_ENDPOINT`, `CRM_FILES_S3_SECURE=true`, `CRM_FILES_S3_ACCESS_KEY`,
`CRM_FILES_S3_SECRET_KEY`, `CRM_FILES_S3_BUCKET`,
`CRM_SMTP_HOST`, `CRM_SMTP_PORT`, `CRM_SMTP_USERNAME`, `CRM_SMTP_PASSWORD`, `CRM_SMTP_STARTTLS=true`,
`CRM_MAIL_FROM`, `CRM_ANTHROPIC_API_KEY` (optional, a **new** key).
For the migration step only: `CRM_MIGRATION_DATABASE_URL` (schema owner user).

**Keycloak:** `KC_HOSTNAME=https://login.example.com`, `KC_DB_URL`, `KC_DB_USERNAME`,
`KC_DB_PASSWORD` (a separate database), `KC_BOOTSTRAP_ADMIN_USERNAME`, `KC_BOOTSTRAP_ADMIN_PASSWORD`,
`CRM_WEB_URL=https://app.example.com`, `CRM_WEB_CLIENT_SECRET` (= Netlify's `OIDC_CLIENT_SECRET`),
`CRM_USER_ADMIN_CLIENT_SECRET`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM`, `SMTP_USER`, `SMTP_PASSWORD`.

## If the Netlify site shows "Page not found" (404)

Every screen in this CRM is rendered per request (it reads the session cookie), so the production
build contains no ready-made HTML. Netlify can only serve it by running its **Next.js adapter**,
which turns the build into serverless Functions plus routing rules. If the adapter does not run,
Netlify deploys the publish folder as a plain static site; with no `index.html` there, every
address - including `/` - returns Netlify's "Page not found" page. That was the symptom on
20 October 2026.

`netlify.toml` now sets `publish = ".next"` (relative to `base = "frontend"`, so it means
`frontend/.next`). Netlify installs the Next.js adapter itself for a Next.js project; do **not**
pin `@netlify/plugin-nextjs` unless the checks below prove it is not running.

Check, in this order:

1. **Was the deploy published?** Deploys → the newest deploy must be marked **Published**. A
   "Skipped" or "Failed" deploy is not live.
2. **Did the adapter run?** Open that deploy → **Deploy summary**. A Next.js deploy lists at least
   one **Function** (and usually one **Edge Function**). Zero functions means the adapter did not
   run, and the 404 is expected.
3. **What was deployed?** In the deploy log look for `Starting to deploy site from '.next'` and
   for the Next.js adapter step. If it says the site was deployed from `frontend` or from an
   empty path, the publish directory in effect is wrong.
4. **Build settings.** Project configuration → Build & deploy → Build settings should show base
   directory `frontend`, build command `npm run build`, publish directory `.next`. The
   repository's `netlify.toml` overrides these values where it sets them.
5. **Is the adapter blocked?** Project configuration → Environment variables: make sure
   `NETLIFY_NEXT_PLUGIN_SKIP` is not set to `true`.
6. After changing any setting: Deploys → **Trigger deploy** → **Clear cache and deploy site**.

**What the logs showed on 24 October 2026 (both sites, same repository):** the deploy log read
`/opt/build/repo/netlify.toml` (so base `frontend` and publish `frontend/.next` *were* applied; the
"UI base directory hides the file" theory is ruled out), Node 22 and Next.js 16.4.2 built fine, but
the log never mentions the Next.js adapter and the deploy step says `0 new function(s) to upload`
with 414 plain files from `frontend/.next`. Zero functions means the adapter did not run, so the
404 is exactly what Netlify serves for a static folder without `index.html`. The fix is the
fallback below: the adapter is now named in `netlify.toml`.

If the Functions count stays 0, the fallback - only with that evidence - is to pin the adapter:
`cd frontend` then `npm install -D @netlify/plugin-nextjs`, add

```toml
[[plugins]]
  package = "@netlify/plugin-nextjs"
```

to `netlify.toml`, and redeploy. Netlify's guidance is not to pin it, so treat this as a
diagnostic step, not the default.

**Expected next symptom:** once routing works but the six environment variables above are still
missing, every page returns Netlify's **500 "Application error"** - `/login` validates them at
request time (`serverConfig()`). Set the six variables on the site (temporary placeholders that
match the formats are enough for a smoke test) before judging the sign-in page.

## Steps still to do

### D2 - private staging (needs your accounts)

1. Create the accounts: a Git host login you already have (GitHub), **Netlify**, a container host,
   a managed PostgreSQL, an S3 bucket provider and an SMTP provider. **You** create them, add
   payment methods and paste secrets into the hosts' settings; I never see them.
2. Buy or choose a domain; create the three names (`app`, `api`, `login`).
3. Database: create two databases (CRM and Keycloak) and the CRM's two users (schema owner and
   restricted app user - see `infrastructure/postgres/init/01-create-roles-and-databases.sh`).
   Run the migrations once: image command `alembic upgrade head` with `CRM_MIGRATION_DATABASE_URL`.
4. Deploy Keycloak, API, worker and the Netlify site with the settings above. Put the staging
   site behind a password (Netlify "password protection") until D3.
5. Create the first administrator **by hand** (the realm has no users):
   Keycloak admin console → realm `crm` → Users → add a user with the realm role `super_admin`,
   set a strong password. Sign in to the web app → **Organisations** → create your organisation and
   invite its first administrator (they get an e-mail to set their password).
6. Run the end-to-end tests against staging (they need test users, so create a separate staging
   realm copy, or test manually with the checklist in `docs/auth.md`).

### D2 on one server (ADR 0021) - needs your server and domain

1. **You:** rent the server and a domain, point `api.…` and `login.…` at the server's address, create two
   private buckets (documents, backups) and an SMTP account, make the backup key pair on your own PC
   (`deploy/one-host/README.md`, "Backups").
2. Harden the server first: [one-host-hardening.md](one-host-hardening.md); `sudo bin/server-check.sh` shows
   no FAIL.
3. On the server: `bin/make_env.py`, fill in the `CHANGE_ME` lines, `bin/check_env.py`, then
   `docker compose --env-file .env up -d --build` (steps and commands: `deploy/one-host/README.md`).
4. Put the same web-app secret into Netlify (`OIDC_CLIENT_SECRET` = `CRM_WEB_CLIENT_SECRET` in `.env`) and the
   other values listed above; create the first administrator by hand (step 5 of D2 above).
5. Make a backup, run `bin/restore-test.sh` and wait for `RESTORE TEST PASSED`. Keep a copy of `.env` in your
   password manager.

If the server is ever lost: **Restoring after a disaster** in `deploy/one-host/README.md`. To update:
`git pull && bin/update.sh`. To go back after a bad update: **Going back** in the same file.

### D3 - go live

Tick **every** item of the checklist below, remove the staging password, announce the address.

## Hardening checklist (all must be ticked before real data goes online)

- [ ] HTTPS everywhere; `CRM_ENVIRONMENT=production` (the API refuses non-HTTPS issuers/file store).
- [x] No test users or development password in the production realm (tested).
- [x] Self sign-up off; administrators invite people (ADR 0004).
- [ ] **All secrets freshly generated** and stored only in the hosts; the Anthropic key shown in chat
      earlier is **revoked** in the Anthropic console and replaced.
- [ ] **Row-level security** (gap-analysis Phase C) finished - or only one organisation online.
      Backend done 2026-10-23 (all 47 tenant tables, ADR 0009); tick after the migrations are on
      the target database and the Playwright suite has passed against them.
- [ ] Database backups on, and a **restore tested**; the file bucket versioned or backed up.
- [ ] *One-server path:*
  - [x] Only the proxy publishes ports (80 and 443); tested on the files and on the running rehearsal.
  - [x] The rehearsal smoke test passes on a PC (22 of 22, 2026-11-03).
  - [x] Firewall (ufw) on, SSH by key only, no root login, automatic security updates: `sudo bin/server-check.sh`
        shows **no FAIL** on the real server (0 FAIL / 0 WARN, 2026-11-06).
  - [x] Backup key pair made on your own PC; the private half is **offline**, never on the server (2026-11-06).
  - [x] The backup bucket's key can add files but not delete them; a lifecycle rule expires old copies
        (`crm-backup`: object creator + viewer only; delete after 30 days; 2026-11-06).
  - [x] `bin/restore-test.sh` says **RESTORE TEST PASSED** on the real server, with real (not empty) data
        (2026-11-06: 1,000 accounts, 1,000 contacts, 301 leads restored).
  - [ ] A copy of the server's `.env` is in your password manager (a backup does not contain it).
  - [x] The Keycloak administration console is closed again (`ADMIN_ALLOWED_IPS=127.0.0.1`; 403 from outside, 2026-11-06).
- [ ] **Upload/PDF sizes verified** on the chosen hosts: Netlify functions limit request and response
      sizes and run time, and our files can be 20 MB. If too small: browser → bucket uploads with
      signed URLs (a small design change, to be done in D1b before staging).
- [ ] Rate limiting and security headers at the edge; logs checked for personal data.
- [ ] Voice (ADR 0023): `CRM_VOICE_BROWSER_ENGINE=false` once real customers' data is spoken (otherwise
  Google/Apple/Microsoft hear the audio); a speech key (`CRM_VOICE_API_KEY`) only if the owner accepts that
  vendor; the `voice` agent stays off until an administrator switches it on.
- [ ] Dependency and image scan (`docker-skills:scan` / Trivy) with no high findings.
- [ ] Phase 21 hardening list in `implementation-plan.md` completed.
- [ ] Monthly cost understood (Netlify credits plan + API host + database + Keycloak host + bucket +
      mail). Exact amounts depend on your provider choices.

## Cost, honestly

Each part has its own price and the totals depend on traffic. Netlify now uses a monthly credit
allowance (a free plan exists and pauses the site when the credits are used up; paid plans start
around $9/month - check Netlify's pricing page). The API, worker, Keycloak and database hosts are
usually the larger part (roughly several dollars each per month on small plans). A single rented
server running docker compose is the cheaper alternative if Netlify is not required.

The one-server path (ADR 0021) replaces the API host, worker, Keycloak host and database by one server
of at least 2 vCPU / 4 GB RAM / 40 GB disk - usually a few to about twenty dollars a month depending on the
provider (check the provider's price page) - and still needs Netlify, the domain, a documents bucket, a
backups bucket and an SMTP provider. 8 GB is more comfortable if the knowledge base is used a lot.
