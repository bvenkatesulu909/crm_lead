# The CRM on one server (ADR 0021)

**Status: prepared and tested on a PC, NOT deployed.** Nothing here has been run on a real server,
no account was created and no money was spent. CLAUDE.md rule 6 still holds: nothing goes online
until you say "go live" and the hardening checklist in `docs/deployment.md` is ticked.

One Linux server runs everything except the web app (Netlify), your documents (an S3 bucket) and
your mail (an SMTP provider):

```
 Browser ──► Netlify (web app)                       Browser ──► login.yourcompany.in
              │ server-side calls                                       │
              ▼                                                         ▼
        api.yourcompany.in ───────────►  caddy (ports 80 + 443, automatic HTTPS)
                                              │                         │
                                            api ◄── worker           keycloak
                                              └────► postgres (+pgvector) ◄┘   (no port open)
```

## What you do (the "V only" part) and what I do

| You | Me |
|---|---|
| Rent a Linux server (Ubuntu LTS, **2 vCPU, 4 GB RAM, 40 GB disk** at least) and a domain | Everything in this folder, tested on a PC |
| Point two names at the server's IP address: `api.…` and `login.…` | Commands for you to run |
| Create two **private** buckets (documents, backups) and an SMTP account | I never log in to your server and never see your secrets |
| Create the backup key pair on your own computer (`age-keygen`) | |

The server commands below are **Linux** (bash), because the server is Linux. Commands for your
Windows PC stay CMD, as everywhere else in this project.

## The steps on the server

1. Install Docker (the provider's guide or Docker's own), open only ports 22, 80 and 443 in the
   firewall, log in with an SSH key (not a password).
2. Get the code and go to this folder: `git clone … && cd crm_lead/deploy/one-host`
3. Write the settings (fresh random secrets; the file is readable by you only):

   ```bash
   python3 bin/make_env.py --api-host api.yourcompany.in --login-host login.yourcompany.in \
       --web-url https://crm.yourcompany.in --acme-email you@yourcompany.in \
       --mail-from no-reply@yourcompany.in
   ```

4. Open `.env` in an editor and replace every `CHANGE_ME` with the value from your provider
   (documents bucket, mail account, backup bucket, the **public** backup key that starts with `age1`).
5. Check it: `python3 bin/check_env.py .env` - it lists what is still wrong, by name, never a secret.
6. Start: `docker compose --env-file .env up -d --build`
   (`migrate` brings the database to the latest version first; the API and worker start after it).
7. Look: `docker compose ps` - every service `running`/`healthy`, `migrate` exited with code 0.
8. Put the values into Netlify (Site configuration → Environment variables): see
   `docs/deployment.md`. `CRM_WEB_CLIENT_SECRET` in `.env` is Netlify's `OIDC_CLIENT_SECRET`.
9. Create the first administrator by hand (the realm has no users) - `docs/deployment.md`, step D2.5.
   For that you need the Keycloak administration console, which is closed to the internet; see
   "Administration console" below.

## Administration console

`https://login.…/admin` answers 403 for everybody unless `ADMIN_ALLOWED_IPS` in `.env` lists your
address. To use it: put your own public IP address there (search "what is my IP"), run
`docker compose --env-file .env up -d caddy`, do your work, then set it back to `127.0.0.1` and run the
same command again. List only your own address, only for as long as you need it.

## What is deliberately not here yet

- Backups, the restore test and the update script: step OH2.
- A rehearsal of the whole thing on a PC with a throwaway certificate, and the server hardening
  guide: step OH3.
- Monitoring on the server (Prometheus/Grafana need memory a small server lacks). Use a free
  external uptime check on `https://api.yourcompany.in/api/v1/health`.

## Files

| File | What it is |
|---|---|
| `docker-compose.yml` | The services; project name `crm-lead-onehost` (never the development stack's) |
| `Caddyfile` | HTTPS, security headers, the two names, metrics hidden, admin console closed |
| `postgres/init/` | First start only: roles, the `crm` and `keycloak` databases, pgvector |
| `.env.example` | The template; the real `.env` is git-ignored |
| `bin/make_env.py` | Writes `.env` with fresh random secrets |
| `bin/check_env.py` | Refuses a placeholder, weak, repeated or development value |
